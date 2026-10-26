//! SWE Gym v2 — the real two-capability benchmark (docs/SWE_Sweycoins_v2.md
//! 14): retrieval (A, pool extension, no direct evidence) + JEV (B, frozen
//! 2019 answers) over the common observation interface. Frozen and
//! reproducible: no live calls, quality only at episode end.

use swe_gym::agent::Policy;
use swe_gym::env::{Action, Observation, SweEnv};
use swe_gym::ledger::{EventKind, Ledger};
use swe_gym::real::{
    evaluate_real, load_real_bench, run_episode_real, RealEnv, RealEqualSplitPolicy,
    RealPipelinePolicy, LOOKUP_MILLI, REAL_BASE_REWARD_MILLI, SCAN_MILLI,
};

fn questions() -> Vec<swe_gym::real::RealQuestion> {
    load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap()
}

#[test]
fn real_fixtures_hit_gold_plus_pinned_extras() {
    let questions = questions();
    let pins = [
        ("auto-renewal", 22usize),
        ("notice-period", 15),
        ("liability-cap", 51),
        ("confidentiality", 23),
        ("liability-secrecy-carveout", 7),
    ];
    for (id, total_fynd) in pins {
        let q = questions.iter().find(|q| q.id == id).unwrap();
        for e in &q.evidence {
            let with_space = format!("\"chunk_id\": \"{e}\"");
            let no_space = format!("\"chunk_id\":\"{e}\"");
            let pos = q
                .fixture_source
                .find(&with_space)
                .or_else(|| q.fixture_source.find(&no_space))
                .unwrap_or_else(|| panic!("{id}: gold chunk {e} missing from fixture"));
            let tail = &q.fixture_source[pos..];
            assert!(
                tail.contains("\"fynd\""),
                "{id}: gold chunk {e} not marked fynd"
            );
        }
        let fynd = q.fixture_source.matches("\"fynd\"").count();
        assert_eq!(fynd, total_fynd, "{id}: fynd count drifted");
    }
}

#[test]
fn real_env_deterministic_and_replayable() {
    let questions = questions();
    let run = || {
        let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
        let mut policy = RealPipelinePolicy::new();
        let report = run_episode_real(&mut env, &mut policy, &questions[1], 3);
        (
            report.reward_milli,
            env.ledger().events().to_vec(),
            env.ledger().balances(),
        )
    };
    let (r1, log1, bal1) = run();
    let (r2, log2, bal2) = run();
    assert_eq!(r1, r2);
    assert_eq!(log1, log2);
    let replayed = Ledger::replay(&log1).unwrap();
    assert_eq!(replayed.balances(), bal1);
}

#[test]
fn real_env_per_step_rewards_sum_to_net() {
    let questions = questions();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let mut policy = RealPipelinePolicy::new();
    let report = run_episode_real(&mut env, &mut policy, &questions[0], 1);
    let spent = env.observation().spent_milli.iter().sum::<u64>();
    let quality = (env.found_count() as f64 / questions[0].required as f64).min(1.0);
    let expected = (quality * REAL_BASE_REWARD_MILLI as f64).round() as i64 - spent as i64;
    assert_eq!(report.reward_milli, expected);
}

#[test]
fn retrieval_has_zero_direct_evidence_and_gates_jev() {
    let questions = questions();
    let q = &questions[0];
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    env.reset(q).unwrap();

    // B before any retrieval: nothing in the pool to verify — zero cost.
    let (_obs, info) = env.step(Action::Invest(1, 5_000)).unwrap();
    assert_eq!(info.cost_milli, 0);
    assert_eq!(env.found_count(), 0);
    assert_eq!(env.observation().new_evidence, 0);

    // A surfaces the pool (1000 milli = 20 chunks at LOOKUP_MILLI).
    let (_obs, info) = env.step(Action::Invest(0, 1_000)).unwrap();
    assert_eq!(info.cost_milli, 20 * LOOKUP_MILLI);
    assert_eq!(env.observation().pool_scanned, 20);
    // Retrieval alone still yields zero verified evidence.
    assert_eq!(env.found_count(), 0);

    // Now B verifies pool chunks against the frozen answers.
    let (_obs, info) = env.step(Action::Invest(1, 5_000)).unwrap();
    assert_eq!(info.cost_milli, 5 * SCAN_MILLI);
    assert!(env.found_count() > 0, "the pool's top chunks are fynd");
    assert!(
        env.observation().last_score_bp > 0,
        "JEV confidence is observable"
    );
}

#[test]
fn interface_signals_are_facit_free_and_consistent() {
    let questions = questions();
    let q = &questions[0];
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    env.reset(q).unwrap();
    let mut policy = RealPipelinePolicy::new();
    policy.episode_start(
        &swe_gym::env::Question {
            id: q.id.clone(),
            qtype: q.qtype,
            budget_milli: q.budget_milli,
        },
        0,
    );
    let mut total_new: u32 = 0;
    loop {
        let obs = env.observation().clone();
        let valid = env.valid_actions();
        let action = policy.act(&obs, &valid);
        let (_o, info) = env.step(action).unwrap();
        let obs2 = env.observation();
        total_new += obs2.new_evidence as u32;
        // Facit-free invariants of the interface.
        assert!(obs2.recent_hit_rate_bp <= 10_000);
        assert!(obs2.pool_scanned <= obs2.pool_total);
        assert_eq!(
            obs2.contradictions, 0,
            "fixtures carry no contradiction data"
        );
        assert_eq!(
            obs2.new_evidence as usize,
            env.found_count() - obs.found as usize
        );
        if info.done {
            break;
        }
    }
    assert_eq!(
        total_new,
        env.found_count() as u32,
        "new_evidence sums to found"
    );
}

#[test]
fn real_env_budget_cap_holds_under_a_pool_burner() {
    let questions = questions();
    struct MaxAPolicy;
    impl Policy for MaxAPolicy {
        fn name(&self) -> &'static str {
            "max-a"
        }
        fn act(&mut self, _obs: &Observation, valid: &[Action]) -> Action {
            let mut best: Option<Action> = None;
            for &a in valid {
                if let Action::Invest(0, amount) = a {
                    if best.map_or(true, |b| match b {
                        Action::Invest(_, ba) => amount > ba,
                        _ => true,
                    }) {
                        best = Some(a);
                    }
                }
            }
            best.unwrap_or(Action::Finish)
        }
    }
    let q = &questions[2]; // liability-cap: 877 chunks
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let mut policy = MaxAPolicy;
    let report = run_episode_real(&mut env, &mut policy, q, 0);
    let balance = env.ledger().balance("exec");
    assert!(balance.spent <= balance.allocated);
    assert_eq!(balance.available(), balance.allocated - balance.spent);
    // A-only: zero verified evidence, so the net is exactly -lookup cost.
    assert_eq!(env.found_count(), 0);
    assert_eq!(
        report.reward_milli,
        -(q.chunks.len() as i64 * LOOKUP_MILLI as i64)
    );
    let kinds: Vec<EventKind> = env.ledger().events().iter().map(|e| e.kind).collect();
    assert_eq!(kinds[0], EventKind::Allocate);
    assert!(kinds.contains(&EventKind::Spend));
}

#[test]
fn benchmark_comparison_pinned() {
    // The comparison the benchmark exists for: the synthetic-trained RL
    // arm vs the strong adaptive baseline (pipeline) and equal split, on
    // the five frozen real questions. No real training data — facit
    // isolation by construction.
    let questions = questions();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);

    let mut learner = swe_gym::train::train_benchmark_learner(7);
    let learner_mean = evaluate_real(&mut env, &mut learner, &questions);
    let pipeline_mean = evaluate_real(&mut env, &mut RealPipelinePolicy::new(), &questions);
    let equal_mean = evaluate_real(&mut env, &mut RealEqualSplitPolicy::new(), &questions);

    // The verdict (recorded, never gamed): the synthetic-trained RL arm
    // regresses against the strong adaptive baseline on real data — it
    // finds the evidence but stops far too late in tier states the
    // synthetic training never visited (state-geometry mismatch, docs 14).
    assert_eq!(learner_mean, LEARNER_REAL2_PIN, "learner mean drifted");
    assert_eq!(pipeline_mean, PIPELINE_REAL2_PIN, "pipeline mean drifted");
    assert_eq!(equal_mean, EQUAL_REAL2_PIN, "equal-split mean drifted");
    assert!(
        learner_mean < pipeline_mean,
        "verdict: the transfer regression must stay measured"
    );
}

const LEARNER_REAL2_PIN: f64 = -29_200.0;
const PIPELINE_REAL2_PIN: f64 = 58_846.2;
const EQUAL_REAL2_PIN: f64 = 22_000.0;
