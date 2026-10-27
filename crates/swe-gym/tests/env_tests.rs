//! SWE Gym v2 acceptance tests — the pre-registered criteria from
//! docs/SWE_Sweycoins_v2.md section 9, plus the env invariants.
//!
//! 1. Calibration gate: oracle >= 1.10 x best baseline on held-out.
//! 2. Learnability: MC-Q learner >= best baseline (>= 3 seeds).
//! 3. Hard budget cap: 0 overspends, ledger invariant.
//! 4. Reproducibility: replay reproduces balances and the trajectory.
//! 5. Real-bench criterion is not testable here (synthetic-only; the real
//!    bench stays the final judge and is evaluated in a separate step).
//! 6. Decision history: every decision is a ledger event.
//! 7. Reward isolation: virtual rewards never inflate executable budget.

use swe_gym::agent::{
    AdaptiveGreedyPolicy, EqualSplitPolicy, McQLearner, Policy, SequentialPolicy,
};
use swe_gym::env::{
    budget_bracket, default_config, Action, EnvConfig, Observation, SweEnv, SyntheticEnv, MAX_STEPS,
};
use swe_gym::ledger::{EventKind, Ledger};
use swe_gym::oracle::oracle_value;
use swe_gym::train::{calibration_gate, default_question_sets, evaluate, run_season};

fn question(id: &str, qtype: u8, budget: u64) -> swe_gym::env::Question {
    swe_gym::env::Question {
        id: id.to_string(),
        qtype,
        budget_milli: budget,
    }
}

// ---------------------------------------------------------------------------
// Env invariants

#[test]
fn per_step_rewards_sum_to_net_terminal_reward() {
    // The env emits per-step rewards (cost debits + terminal quality);
    // their sum must equal the spec's net formula — the accounting
    // identity that keeps the learner's state Markov.
    let config = default_config();
    for qtype in 0..4u8 {
        let q = question("identity", qtype, 100_000);
        let mut env = SyntheticEnv::new(config.clone());
        env.reset(&q).unwrap();
        let mut policy = EqualSplitPolicy::new();
        policy.episode_start(&q, 0);
        let mut sum: i64 = 0;
        loop {
            let valid = env.valid_actions();
            let action = policy.act(env.observation(), &valid);
            let (_obs, info) = env.step(action).unwrap();
            sum += info.reward_milli;
            if info.done {
                break;
            }
        }
        let obs = env.observation();
        let spent = obs.spent_milli.iter().sum::<u64>();
        let net = swe_gym::env::terminal_reward(&config, qtype, &obs.tiers, spent);
        assert_eq!(sum, net, "type {qtype}: step sum {sum} != net {net}");
    }
}

#[test]
fn deterministic_trajectory_and_replay() {
    let config = default_config();
    let q = question("det", 1, 100_000);

    let mut run = |_| {
        let mut env = SyntheticEnv::new(config.clone());
        env.reset(&q).unwrap();
        let mut policy = EqualSplitPolicy::new();
        policy.episode_start(&q, 0);
        let mut events_log: Vec<swe_gym::ledger::Event> = Vec::new();
        let mut reward = 0;
        loop {
            let valid = env.valid_actions();
            let action = policy.act(env.observation(), &valid);
            let (_obs, info) = env.step(action).unwrap();
            events_log = env.ledger().events().to_vec();
            if info.done {
                reward = info.reward_milli;
                break;
            }
        }
        (reward, events_log, env.ledger().balances())
    };

    let (r1, log1, bal1) = run(());
    let (r2, log2, bal2) = run(());

    // Same policy, same env -> identical trajectory and reward (criterion 4).
    assert_eq!(r1, r2);
    assert_eq!(log1, log2);
    // Ledger replay reproduces the materialized balances exactly.
    let replayed = Ledger::replay(&log1).unwrap();
    assert_eq!(replayed.balances(), bal1);
}

#[test]
fn invalid_and_masked_actions_fail_loudly() {
    let config = default_config();
    let q = question("mask", 2, 20_000);
    let mut env = SyntheticEnv::new(config);
    env.reset(&q).unwrap();

    // Masking: nothing above remaining budget is offered.
    let valid = env.valid_actions();
    for a in &valid {
        if let Action::Invest(_, amount) = a {
            assert!(*amount <= 20_000, "masked invest {amount} exceeds budget");
        }
    }
    // Overspend is rejected loudly.
    assert!(env.step(Action::Invest(0, 20_001)).is_err());
    assert!(env.step(Action::Invest(0, 5_000)).is_ok());
    // After stopping a strategy it is not investable anymore.
    assert!(env.step(Action::Stop(1)).is_ok());
    let valid = env.valid_actions();
    assert!(
        !valid.iter().any(|a| matches!(a, Action::Invest(1, _))),
        "stopped strategy still investable"
    );
    assert!(env.step(Action::Invest(1, 5_000)).is_err());
    // Finish ends the episode.
    let (_obs, info) = env.step(Action::Finish).unwrap();
    assert!(info.done);
    assert!(env.valid_actions().is_empty());
}

#[test]
fn budget_cap_is_hard_and_booked_through_the_ledger() {
    let config = default_config();
    // A greedy stress policy: always the max affordable amount, cycling.
    struct MaxInvestPolicy {
        next: usize,
    }
    impl Policy for MaxInvestPolicy {
        fn name(&self) -> &'static str {
            "max-invest"
        }
        fn act(&mut self, _obs: &Observation, valid: &[Action]) -> Action {
            for _ in 0..3 {
                let s = self.next;
                self.next = (s + 1) % 3;
                let mut best: Option<Action> = None;
                for &a in valid {
                    if let Action::Invest(i, amount) = a {
                        if i == s
                            && best.map_or(true, |b| match b {
                                Action::Invest(_, ba) => amount > ba,
                                _ => true,
                            })
                        {
                            best = Some(a);
                        }
                    }
                }
                if let Some(a) = best {
                    return a;
                }
            }
            Action::Finish
        }
    }

    for qtype in 0..4u8 {
        for budget in [60_000, 100_000, 140_000] {
            let q = question("stress", qtype, budget);
            let mut env = SyntheticEnv::new(config.clone());
            env.reset(&q).unwrap();
            let mut policy = MaxInvestPolicy { next: 0 };
            loop {
                let valid = env.valid_actions();
                let action = policy.act(env.observation(), &valid);
                let (_obs, info) = env.step(action).unwrap();
                if info.done {
                    break;
                }
            }
            let balance = env.ledger().balance("exec");
            let spent = env.observation().spent_milli.iter().sum::<u64>();
            // Criterion 3: never above allocation, never negative.
            assert_eq!(balance.spent, spent);
            assert!(balance.spent <= balance.allocated);
            assert_eq!(balance.available(), balance.allocated - balance.spent);
            // Money only moves through the ledger (criterion 6).
            let kinds: Vec<EventKind> = env.ledger().events().iter().map(|e| e.kind).collect();
            assert_eq!(kinds[0], EventKind::Allocate);
            assert!(kinds.contains(&EventKind::Spend));
        }
    }
}

#[test]
fn reward_pool_can_never_inflate_executable_budget() {
    let config = default_config();
    let q = question("reward-iso", 3, 100_000);
    let mut env = SyntheticEnv::new(config.clone());
    env.reset(&q).unwrap();
    // Solve t3 cheaply: 10 coins into C reaches full quality.
    assert!(env.step(Action::Invest(2, 10_000)).is_ok());
    let available_before = env.ledger().balance("exec").available();
    let (_obs, info) = env.step(Action::Finish).unwrap();
    assert!(info.done);
    assert!(info.reward_milli > 0);
    // Criterion 7: the reward landed in the virtual pool; the executable
    // balance is untouched by it.
    assert_eq!(env.ledger().rewards("training"), info.reward_milli as u64);
    let balance = env.ledger().balance("exec");
    assert_eq!(balance.available(), available_before);
    assert_eq!(balance.allocated, balance.spent + balance.available());
}

#[test]
fn max_steps_terminates_and_still_scores() {
    let config = default_config();
    let q = question("maxsteps", 0, 100_000);
    let mut env = SyntheticEnv::new(config);
    env.reset(&q).unwrap();
    let mut steps = 0;
    loop {
        let valid = env.valid_actions();
        // Never finish; grind the cheapest action available.
        let invest = valid
            .iter()
            .find(|a| matches!(a, Action::Invest(_, _)))
            .copied()
            .unwrap_or(Action::Finish);
        let (_obs, info) = env.step(invest).unwrap();
        steps += 1;
        if info.done {
            assert_eq!(info.reason, "max steps");
            assert!(steps <= MAX_STEPS as u32 + 1);
            break;
        }
    }
}

// ---------------------------------------------------------------------------
// Oracle

#[test]
fn oracle_pinned_values() {
    let config = default_config();
    // Exact DP optima (discrete amounts 1/5/10/20 with leftover loss);
    // distinct mixes per type prove the world has learnable structure.
    assert_eq!(oracle_value(&config, 0, 100_000), 80_000); // C4 alone
    assert_eq!(oracle_value(&config, 1, 100_000), 130_000); // A2 + B2 + C2
    assert_eq!(oracle_value(&config, 2, 100_000), 130_000); // B4 + C2
    assert_eq!(oracle_value(&config, 3, 100_000), 190_000); // C4 alone
}

#[test]
fn oracle_dominates_every_baseline_on_every_type() {
    let config = default_config();
    for qtype in 0..4u8 {
        let q = question("dom", qtype, 100_000);
        let ov = oracle_value(&config, qtype, 100_000);
        for mut policy in [
            Box::new(EqualSplitPolicy::new()) as Box<dyn Policy>,
            Box::new(SequentialPolicy::new()),
            Box::new(AdaptiveGreedyPolicy::new()),
        ] {
            let r = evaluate(&config, policy.as_mut(), &[q.clone()]);
            assert!(
                ov as f64 > r,
                "type {qtype}: oracle {ov} must beat {} ({r})",
                policy.name()
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Calibration gate + learner (the pre-registered acceptance criteria)

#[test]
fn calibration_gate_passes_on_held_out() {
    let config = default_config();
    let (_train, held_out) = default_question_sets();
    let gate = calibration_gate(&config, &held_out);
    assert!(
        gate.passed,
        "oracle {:.0} vs best baseline {:.0} (ratio {:.2}, need >= 1.10)",
        gate.oracle_mean, gate.best_baseline_mean, gate.margin_ratio
    );
}

#[test]
fn learner_beats_best_baseline_on_held_out() {
    let config = default_config();
    let (train, held_out) = default_question_sets();

    let mut baseline_means = [
        evaluate(&config, &mut EqualSplitPolicy::new(), &held_out),
        evaluate(&config, &mut SequentialPolicy::new(), &held_out),
        evaluate(&config, &mut AdaptiveGreedyPolicy::new(), &held_out),
    ];
    let best_baseline = baseline_means.iter().cloned().fold(f64::MIN, f64::max);

    // Criterion 2: learner >= best baseline, averaged over >= 3 seeds.
    let mut learner_means = Vec::new();
    for seed in [7u64, 11, 23] {
        let mut learner = McQLearner::new(seed);
        run_season(&config, &mut learner, &train);
        learner.set_eval(true);
        learner_means.push(evaluate(&config, &mut learner, &held_out));
    }
    let learner_mean: f64 = learner_means.iter().sum::<f64>() / learner_means.len() as f64;

    assert!(
        learner_mean >= best_baseline,
        "learner {learner_mean:.0} < best baseline {best_baseline:.0} (seeds {learner_means:?}, baselines {baseline_means:?})"
    );

    // Learnability signal (informative): the learner must capture a
    // meaningful fraction of the oracle ceiling, or the world is too hard
    // to learn and the experiment needs redesign.
    let oracle_mean = calibration_gate(&config, &held_out).oracle_mean;
    assert!(
        learner_mean >= 0.70 * oracle_mean,
        "learner {learner_mean:.0} < 70% of oracle {oracle_mean:.0}"
    );

    baseline_means.sort_by(|a, b| b.partial_cmp(a).unwrap());
}

#[test]
fn learner_generalizes_across_unseen_budgets() {
    let config = default_config();
    let (train, held_out) = default_question_sets();
    let mut learner = McQLearner::new(42);
    run_season(&config, &mut learner, &train);
    learner.set_eval(true);

    // Held-out budgets (60k/140k) are unseen during training (all train
    // questions carry 100k); the policy must transfer.
    for q in &held_out {
        let report = swe_gym::train::run_episode(&config, &mut learner, q, 7);
        assert!(report.steps > 0);
        // Sanity: positive expected net value on every held-out question.
        assert!(
            report.reward_milli > 0,
            "{}: learner lost money ({})",
            q.id,
            report.reward_milli
        );
    }
}

#[test]
fn state_indexing_and_brackets_are_stable() {
    // The learner's state key relies on these quantizations; pin them so
    // a silent change to the state space cannot drift the policy.
    assert_eq!(budget_bracket(19_999), 0);
    assert_eq!(budget_bracket(20_000), 1);
    assert_eq!(budget_bracket(49_999), 1);
    assert_eq!(budget_bracket(50_000), 2);
    assert_eq!(budget_bracket(79_999), 2);
    assert_eq!(budget_bracket(80_000), 3);
    let obs = Observation {
        question_id: "x".into(),
        qtype: 1,
        remaining_milli: 50_000,
        bracket: budget_bracket(50_000),
        tiers: [1, 2, 3],
        found: 0,
        new_evidence: 0,
        contradictions: 0,
        recent_hit_rate_bp: 0,
        last_score_bp: 0,
        pool_scanned: 0,
        pool_total: 0,
        pool_extension_yielded: 0,
        zero_hit_streak: 0,
        next_rank_bp: 0,
        docs_remaining: 0,
        docs_with_hits: 0,
        new_doc_hit: 0,
        statuses: [swe_gym::env::Status::Active; 3],
        spent_milli: [0; 3],
        steps: 0,
    };
    assert_eq!(obs.bracket, 2);
}
