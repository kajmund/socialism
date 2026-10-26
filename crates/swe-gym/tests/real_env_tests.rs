//! SWE Gym v2 step 6 — frozen real bench (docs/SWE_Sweycoins_v2.md).
//!
//! The real env is replay-based: every JEV answer comes from the frozen
//! 2019 fixtures, quality is evaluated against gold only at episode end,
//! and all money flows through the ledger with per-step accounting.
//! Criterion 5 (learner vs equal-split on the real bench) is measured
//! here with pre-registered pins; its verdict is reported, never gamed.

use swe_gym::agent::{McQLearner, Policy};
use swe_gym::env::{default_config, Action, Observation};
use swe_gym::ledger::{EventKind, Ledger};
use swe_gym::real::{
    evaluate_real, load_real_bench, run_episode_real, RealAdaptivePolicy, RealEnv,
    RealEqualSplitPolicy, RealSequentialPolicy, REAL_BASE_REWARD_MILLI,
};
use swe_gym::train::{default_question_sets, run_season};

fn questions() -> Vec<swe_gym::real::RealQuestion> {
    load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap()
}

// ---------------------------------------------------------------------------
// Frozen data + env invariants

#[test]
fn real_fixtures_hit_gold_plus_pinned_extras() {
    let questions = questions();
    // gold + extra fynd, pinned per question (v1's captured JEV runs).
    let pins = [
        ("auto-renewal", 22usize),
        ("notice-period", 15),
        ("liability-cap", 51),
        ("confidentiality", 23),
        ("liability-secrecy-carveout", 7),
    ];
    for (id, total_fynd) in pins {
        let q = questions.iter().find(|q| q.id == id).unwrap();
        // Every gold evidence chunk must be answered "fynd" in the fixture
        // (v1's pinned 100% hit rate, no misses). The fixture formatting is
        // inconsistent (some entries lack the space after "chunk_id":), so
        // both spellings are accepted.
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
        let mut policy = RealEqualSplitPolicy::new();
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
    let mut policy = RealSequentialPolicy::new(0);
    let report = run_episode_real(&mut env, &mut policy, &questions[0], 1);
    // net == round(quality x base) - total spent, with quality = found/required.
    let spent = env.observation().spent_milli.iter().sum::<u64>();
    let quality = (env.found_count() as f64 / questions[0].required as f64).min(1.0);
    let expected = (quality * REAL_BASE_REWARD_MILLI as f64).round() as i64 - spent as i64;
    assert_eq!(report.reward_milli, expected);
    assert!(report.reward_milli > 0, "similarity-first should profit");
}

#[test]
fn real_env_budget_cap_and_settle_releases_remainder() {
    let questions = questions();
    // A greedy stress policy: always the max affordable invest in A, never
    // finishing — the budget cap must hold regardless.
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
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let mut policy = MaxAPolicy;
    let report = run_episode_real(&mut env, &mut policy, &questions[0], 0);
    let balance = env.ledger().balance("exec");
    // Criterion 3: never above allocation, never negative, replayable.
    assert!(balance.spent <= balance.allocated);
    assert_eq!(balance.available(), balance.allocated - balance.spent);
    let spent = env.observation().spent_milli.iter().sum::<u64>();
    assert!(spent <= questions[0].budget_milli);
    let kinds: Vec<EventKind> = env.ledger().events().iter().map(|e| e.kind).collect();
    assert_eq!(kinds[0], EventKind::Allocate);
    assert!(kinds.contains(&EventKind::Spend));
    // Blind max-invest burns the whole budget: quality caps at 1.0 while
    // cost keeps growing, so the net is exactly base - budget. The
    // accounting identity must hold, not a profit.
    let quality = (env.found_count() as f64 / questions[0].required as f64).min(1.0);
    let expected = (quality * REAL_BASE_REWARD_MILLI as f64).round() as i64 - spent as i64;
    assert_eq!(report.reward_milli, expected);
    assert_eq!(report.reward_milli, -100_000); // 100k quality - 200k spent
}

#[test]
fn similarity_order_dominates_document_order_on_all_real_questions() {
    // v1's core real-bench finding, re-confirmed in the v2 env. Stop-rule
    // artifacts (extra-fynd tails keep plateau detectors scanning) make
    // net-with-stop-rules an unfair comparison, so both orders get the
    // same fixed investment and we compare the quality achieved: the
    // similarity order must reach strictly more findings per coin than
    // document order on every question.
    struct FixedInvest {
        s: usize,
        remaining: u64,
    }
    impl Policy for FixedInvest {
        fn name(&self) -> &'static str {
            "fixed-invest"
        }
        fn episode_start(&mut self, _q: &swe_gym::env::Question, _i: u64) {
            self.remaining = 50_000;
        }
        fn act(&mut self, _obs: &Observation, valid: &[Action]) -> Action {
            if self.remaining == 0 {
                return Action::Finish;
            }
            let amount = [20_000u64, 10_000, 5_000, 1_000]
                .iter()
                .copied()
                .find(|&a| a <= self.remaining)
                .unwrap_or(0);
            if amount == 0 || !valid.contains(&Action::Invest(self.s, amount)) {
                return Action::Finish;
            }
            self.remaining -= amount;
            Action::Invest(self.s, amount)
        }
    }
    let questions = questions();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    for q in &questions {
        let mut sim = FixedInvest { s: 0, remaining: 0 };
        let mut doc = FixedInvest { s: 1, remaining: 0 };
        let ra = run_episode_real(&mut env, &mut sim, q, 0).reward_milli;
        let rb = run_episode_real(&mut env, &mut doc, q, 0).reward_milli;
        assert!(
            ra > rb,
            "{}: similarity {ra} must beat document order {rb}",
            q.id
        );
    }
}

// ---------------------------------------------------------------------------
// Criterion 5: does the synthetic-trained learner transfer to real questions?

#[test]
fn transfer_gate_real_bench_pinned() {
    // Pre-registered setup: learner trained on the synthetic season
    // (facit-isolated — the real bench is never training data), then
    // evaluated against the frozen real questions with the pre-registered
    // observable type rule (chunk-count buckets). The measured means are
    // pinned so any drift in the setup fails loudly; the criterion-5
    // verdict itself is reported by the example and the docs.
    let config = default_config();
    let (train, _) = default_question_sets();
    let mut learner = McQLearner::new(7);
    run_season(&config, &mut learner, &train);
    learner.set_eval(true);

    let questions = questions();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let learner_mean = evaluate_real(&mut env, &mut learner, &questions);
    let equal_mean = evaluate_real(&mut env, &mut RealEqualSplitPolicy::new(), &questions);
    let seq_mean = evaluate_real(&mut env, &mut RealSequentialPolicy::new(0), &questions);
    let adapt_mean = evaluate_real(&mut env, &mut RealAdaptivePolicy::new(), &questions);

    // Pins — measured, then frozen (see docs/SWE_Sweycoins_v2.md 11.2).
    // Verdict (recorded, not gamed): learner -100k < equal-split +22k —
    // the synthetic-trained policy regresses on the real bench, so
    // criterion 5 FAILS. The decision point follows in the docs.
    assert_eq!(learner_mean, LEARNER_REAL_PIN, "learner mean drifted");
    assert_eq!(equal_mean, EQUAL_REAL_PIN, "equal-split mean drifted");
    assert_eq!(seq_mean, SEQ_REAL_PIN, "sequential mean drifted");
    assert_eq!(adapt_mean, ADAPT_REAL_PIN, "adaptive mean drifted");
    assert!(
        learner_mean < equal_mean,
        "criterion 5: the transfer verdict is regression — keep it measured"
    );
}

const LEARNER_REAL_PIN: f64 = -100_000.0;
const EQUAL_REAL_PIN: f64 = 22_000.0;
const SEQ_REAL_PIN: f64 = 20_000.0;
const ADAPT_REAL_PIN: f64 = 44_000.0;
