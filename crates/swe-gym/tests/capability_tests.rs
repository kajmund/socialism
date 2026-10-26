//! SWE Gym v2 — level-2 capability world (docs/SWE_Sweycoins_v2.md 12):
//! three genuinely different capabilities (retrieval/JEV/LLM) where no
//! strategy is always best, vs the adaptive rule and the oracle. The
//! stop decision is the point: the learner must stop near the oracle's
//! cost, not just reach full quality.

use swe_gym::agent::{
    AdaptiveGreedyPolicy, EqualSplitPolicy, McQLearner, Policy, SequentialPolicy,
};
use swe_gym::env::capability_config;
use swe_gym::oracle::{oracle_policy_cost, oracle_value};
use swe_gym::train::{calibration_gate, default_question_sets, evaluate, run_episode, run_season};

#[test]
fn capability_oracle_pinned() {
    let config = capability_config();
    // Distinct optimal mixes per type (verified against the DP):
    // t0 retrieval-led mix, t1 JEV-led mix, t2 LLM alone, t3 balanced mix.
    assert_eq!(oracle_value(&config, 0, 100_000), ORACLE_T0);
    assert_eq!(oracle_value(&config, 1, 100_000), ORACLE_T1);
    assert_eq!(oracle_value(&config, 2, 100_000), ORACLE_T2);
    assert_eq!(oracle_value(&config, 3, 100_000), ORACLE_T3);
}

#[test]
fn capability_gate_passes_on_held_out() {
    let config = capability_config();
    let (_train, held_out) = default_question_sets();
    let gate = calibration_gate(&config, &held_out);
    assert!(
        gate.passed,
        "oracle {:.0} vs best baseline {:.0} (ratio {:.2}, need >= 1.10)",
        gate.oracle_mean, gate.best_baseline_mean, gate.margin_ratio
    );
}

#[test]
fn learner_beats_adaptive_rule_on_held_out() {
    let config = capability_config();
    let (train, held_out) = default_question_sets();
    let mut baseline_means = [
        evaluate(&config, &mut EqualSplitPolicy::new(), &held_out),
        evaluate(&config, &mut SequentialPolicy::new(), &held_out),
        evaluate(&config, &mut AdaptiveGreedyPolicy::new(), &held_out),
    ];
    let best_baseline = baseline_means.iter().cloned().fold(f64::MIN, f64::max);

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
    let oracle_mean = calibration_gate(&config, &held_out).oracle_mean;
    assert!(
        learner_mean >= 0.70 * oracle_mean,
        "learner {learner_mean:.0} < 70% of oracle {oracle_mean:.0}"
    );
    // Pin the measured means so drift fails loudly.
    assert_eq!(learner_mean, LEARNER_PIN);
    assert_eq!(best_baseline, BEST_BASELINE_PIN);
    baseline_means.sort_by(|a, b| b.partial_cmp(a).unwrap());
}

#[test]
fn learner_stops_near_oracle_cost() {
    // The user's point 1: finding the evidence is not enough — the stop
    // decision is what makes the budget manager valuable. The learner
    // must finish within 1.5x the oracle's optimal spend on held-out
    // questions (pinned threshold, measured below).
    let config = capability_config();
    let (train, held_out) = default_question_sets();
    let mut learner = McQLearner::new(7);
    run_season(&config, &mut learner, &train);
    learner.set_eval(true);

    let mut learner_cost = 0u64;
    let mut oracle_cost = 0u64;
    for (i, q) in held_out.iter().enumerate() {
        let report = run_episode(&config, &mut learner, q, i as u64);
        learner_cost += report.spent_milli;
        oracle_cost += oracle_policy_cost(&config, q.qtype, q.budget_milli);
    }
    assert!(learner_cost > 0 && oracle_cost > 0);
    let ratio = learner_cost as f64 / oracle_cost as f64;
    assert!(
        ratio <= STOP_COST_RATIO,
        "learner spent {learner_cost} vs oracle {oracle_cost} (ratio {ratio:.2}, need <= {STOP_COST_RATIO})"
    );
    assert_eq!(
        (learner_cost, oracle_cost),
        (LEARNER_COST_PIN, ORACLE_COST_PIN)
    );
}

// Pins — filled from the first measured run.
const ORACLE_T0: i64 = 85_000;
const ORACLE_T1: i64 = 85_000;
const ORACLE_T2: i64 = 90_000;
const ORACLE_T3: i64 = 85_000;
const LEARNER_PIN: f64 = 82_375.0;
const BEST_BASELINE_PIN: f64 = 58_750.0;
const STOP_COST_RATIO: f64 = 1.5;
const LEARNER_COST_PIN: u64 = 146_000;
const ORACLE_COST_PIN: u64 = 110_000;
