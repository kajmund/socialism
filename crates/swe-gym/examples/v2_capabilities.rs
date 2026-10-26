//! SWE Gym v2 — level-2 capability world (docs/SWE_Sweycoins_v2.md 12):
//! three genuinely different capabilities (retrieval / JEV / LLM) where
//! no strategy is always best. The learner's stop decision is measured
//! against the oracle's optimal cost, not just its value.
//!
//! Run with: cargo run --example v2_capabilities

use swe_gym::agent::{McQLearner, Policy};
use swe_gym::env::capability_config;
use swe_gym::oracle::{oracle_policy_cost, oracle_value};
use swe_gym::train::{calibration_gate, default_question_sets, evaluate, run_episode, run_season};

fn main() {
    let config = capability_config();
    let (train, held_out) = default_question_sets();

    println!("== SWE Gym v2 level-2 capability world ==");
    println!(
        "data: synthetic, deterministic; capabilities A=retrieval (cap .5), B=JEV (cap .75), C=LLM (cap 1.0)\n"
    );

    println!("-- calibration gate --");
    let gate = calibration_gate(&config, &held_out);
    for (name, mean) in [
        ("equal-split", gate.baseline_means[0]),
        ("sequential", gate.baseline_means[1]),
        ("adaptive (plateau)", gate.baseline_means[2]),
    ] {
        println!("  {name:<20} {:>9.0}", mean);
    }
    println!("  {:<20} {:>9.0}", "oracle", gate.oracle_mean);
    println!(
        "  gate: {} (oracle / best baseline = {:.2}, need >= 1.10)\n",
        if gate.passed { "PASS" } else { "FAIL" },
        gate.margin_ratio
    );

    let mut learner = McQLearner::new(7);
    run_season(&config, &mut learner, &train);
    learner.set_eval(true);
    let learner_mean = evaluate(&config, &mut learner, &held_out);
    println!("-- held-out (unseen budgets 60k/140k) --");
    println!("  {:<20} {:>9.0}", "mc-q-learner", learner_mean);
    println!(
        "  learner / oracle = {:.2}\n",
        learner_mean / gate.oracle_mean
    );

    println!("-- stop decision: spend vs the oracle's optimal cost --");
    let mut learner_cost = 0u64;
    let mut oracle_cost = 0u64;
    for (i, q) in held_out.iter().enumerate() {
        let report = run_episode(&config, &mut learner, q, i as u64);
        learner_cost += report.spent_milli;
        oracle_cost += oracle_policy_cost(&config, q.qtype, q.budget_milli);
    }
    println!(
        "  learner spend {:>7}   oracle optimal spend {:>7}   ratio {:.2} (acceptance <= 1.5)",
        learner_cost,
        oracle_cost,
        learner_cost as f64 / oracle_cost as f64
    );

    println!("\n-- per type (oracle value / optimal mix) --");
    for t in 0..4u8 {
        let mix = match t {
            0 => "retrieval-ledd (A3+B2+C1)",
            1 => "JEV-ledd (B4+C1)",
            2 => "LLM ensam (C4)",
            _ => "balanserad (A3+B2+C1)",
        };
        println!(
            "  t{t}: oracle {}   optimal cost {}   mix: {mix}",
            oracle_value(&config, t, 100_000),
            oracle_policy_cost(&config, t, 100_000)
        );
    }
    println!("\n(no facit in the observation; quality is revealed only at");
    println!(" episode end. Real Golden Questions come after this works.)");
}
