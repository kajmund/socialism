//! SWE Gym v2 — synergy world (docs/SWE_Sweycoins_v2.md 13): the final
//! synthetic experiment before freezing the gym architecture.
//!
//! Complementary capabilities with delayed return: A (retrieval) yields
//! zero direct quality but unlocks B (JEV, 4x cheaper per tier), and C
//! (LLM) can only synthesize what B has extracted. The learner must
//! discover "invest in A first" on the chain types and "skip A" where
//! retrieval does not pay — pure delayed-return credit assignment.
//!
//! Pipeline: online season (200/type) -> deterministic coverage sweep
//! (400/type, count-driven, seed-independent) -> offline replay fit
//! (value iteration over all collected episodes).

use swe_gym::agent::{McQLearner, Policy};
use swe_gym::env::{synergy_config, Question, SweEnv, SyntheticEnv};
use swe_gym::oracle::{oracle_policy_cost, oracle_value};
use swe_gym::train::{calibration_gate, default_question_sets, evaluate, run_episode, run_season};

fn train_learner(seed: u64) -> McQLearner {
    let config = synergy_config();
    let mut learner = McQLearner::new(seed);
    let mut train = Vec::new();
    for qtype in 0..4u8 {
        for i in 0..200u32 {
            train.push(Question {
                id: format!("t{qtype}-{i}"),
                qtype,
                budget_milli: 100_000,
            });
        }
    }
    run_season(&config, &mut learner, &train);
    // Coverage sweep: complete the visited-state set deterministically,
    // so the replay fit's data no longer depends on exploration luck.
    learner.set_sweep(true);
    let mut sweep = Vec::new();
    for qtype in 0..4u8 {
        for i in 0..400u32 {
            sweep.push(Question {
                id: format!("s{qtype}-{i}"),
                qtype,
                budget_milli: 100_000,
            });
        }
    }
    run_season(&config, &mut learner, &sweep);
    learner.set_sweep(false);
    learner.replay_fit(100);
    learner.set_eval(true);
    learner
}

#[test]
fn synergy_oracle_pinned() {
    let config = synergy_config();
    // t0 the chain pays, t1 skip retrieval, t2/t3 full-synthesis mixes.
    assert_eq!(oracle_value(&config, 0, 100_000), 69_000);
    assert_eq!(oracle_value(&config, 1, 100_000), 57_500);
    assert_eq!(oracle_value(&config, 2, 100_000), 74_000);
    assert_eq!(oracle_value(&config, 3, 100_000), 74_000);
    assert_eq!(oracle_policy_cost(&config, 0, 100_000), 31_000);
    assert_eq!(oracle_policy_cost(&config, 1, 100_000), 30_000);
    assert_eq!(oracle_policy_cost(&config, 2, 100_000), 26_000);
    assert_eq!(oracle_policy_cost(&config, 3, 100_000), 26_000);
}

#[test]
fn synergy_gate_passes_on_held_out() {
    let config = synergy_config();
    let (_train, held_out) = default_question_sets();
    let gate = calibration_gate(&config, &held_out);
    assert!(
        gate.passed,
        "oracle {:.0} vs best baseline {:.0} (ratio {:.2}, need >= 1.10)",
        gate.oracle_mean, gate.best_baseline_mean, gate.margin_ratio
    );
}

#[test]
fn learner_beats_baselines_with_delayed_return() {
    let config = synergy_config();
    let (_train, held_out) = default_question_sets();
    let gate = calibration_gate(&config, &held_out);
    let best_baseline = gate.best_baseline_mean;

    let mut means = Vec::new();
    for seed in [7u64, 11, 23] {
        let mut learner = train_learner(seed);
        means.push(evaluate(&config, &mut learner, &held_out));
    }
    let learner_mean = means.iter().sum::<f64>() / means.len() as f64;
    // Strong margin: the learner must not just tie the baseline — the
    // delayed-return discovery is the point.
    assert!(
        learner_mean >= 1.5 * best_baseline,
        "learner {learner_mean:.0} < 1.5x best baseline {best_baseline:.0} (seeds {means:?})"
    );
    assert!(
        learner_mean >= 0.85 * gate.oracle_mean,
        "learner {learner_mean:.0} < 85% of oracle {:.0}",
        gate.oracle_mean
    );
    // Seed stability: the sweep made coverage deterministic; every seed
    // must land in the same band (measured spread ~2k).
    let spread = means.iter().cloned().fold(f64::MIN, f64::max)
        - means.iter().cloned().fold(f64::MAX, f64::min);
    assert!(
        spread <= 5_000.0,
        "seed spread {spread:.0} too wide: {means:?}"
    );
    assert_eq!(learner_mean, LEARNER_MEAN_PIN);
}

#[test]
fn learner_discovers_retrieval_first_and_skips_it_where_it_pays() {
    // The delayed-return probes: on the chain type the learner's FIRST
    // investment goes to retrieval (A) although A yields zero direct
    // quality; on the skip type it does NOT start with A.
    let config = synergy_config();
    let (_train, held_out) = default_question_sets();
    let mut learner = train_learner(7);

    let t0 = held_out.iter().find(|q| q.id == "held-t0-b60000").unwrap();
    let t1 = held_out.iter().find(|q| q.id == "held-t1-b60000").unwrap();

    let first = |learner: &mut McQLearner, q: &Question| {
        let mut env = SyntheticEnv::new(config.clone());
        env.reset(q).unwrap();
        learner.episode_start(q, 0);
        let valid = env.valid_actions();
        learner.act(env.observation(), &valid)
    };

    let a0 = first(&mut learner, t0);
    assert!(
        matches!(a0, swe_gym::env::Action::Invest(0, _)),
        "chain type must start with retrieval, got {a0:?}"
    );
    let a1 = first(&mut learner, t1);
    assert!(
        !matches!(a1, swe_gym::env::Action::Invest(0, _)),
        "skip type must not start with retrieval, got {a1:?}"
    );

    // And the resulting episodes must be near-oracle.
    let r0 = run_episode(&config, &mut learner, t0, 0).reward_milli;
    let r1 = run_episode(&config, &mut learner, t1, 0).reward_milli;
    assert!(r0 >= 55_000, "chain type reward {r0} too low");
    assert!(r1 >= 40_000, "skip type reward {r1} too low");
}

#[test]
fn learner_stops_near_oracle_cost_in_synergy_world() {
    let config = synergy_config();
    let (_train, held_out) = default_question_sets();
    let mut learner = train_learner(7);
    let mut learner_cost = 0u64;
    let mut oracle_cost = 0u64;
    for (i, q) in held_out.iter().enumerate() {
        let report = run_episode(&config, &mut learner, q, i as u64);
        learner_cost += report.spent_milli;
        oracle_cost += oracle_policy_cost(&config, q.qtype, q.budget_milli);
    }
    let ratio = learner_cost as f64 / oracle_cost as f64;
    assert!(
        ratio <= 1.5,
        "learner spent {learner_cost} vs oracle {oracle_cost} (ratio {ratio:.2})"
    );
    assert_eq!(
        (learner_cost, oracle_cost),
        (LEARNER_COST_PIN, ORACLE_COST_PIN)
    );
}

const LEARNER_MEAN_PIN: f64 = 63_125.0;
const LEARNER_COST_PIN: u64 = 270_000;
const ORACLE_COST_PIN: u64 = 226_000;
