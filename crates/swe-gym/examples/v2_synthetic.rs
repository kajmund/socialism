//! SWE Gym v2 synthetic experiment — calibration gate, training season,
//! held-out evaluation. Offline only (no external services): every score
//! printed here states its data (synthetic, deterministic), seed and cost.
//!
//! Run with: cargo run --example v2_synthetic

use swe_gym::agent::{
    AdaptiveGreedyPolicy, EqualSplitPolicy, McQLearner, Policy, SequentialPolicy,
};
use swe_gym::env::default_config;
use swe_gym::train::{calibration_gate, default_question_sets, evaluate, run_season};

fn main() {
    let config = default_config();
    let (train, held_out) = default_question_sets();

    println!("== SWE Gym v2 synthetic experiment ==");
    println!(
        "data: synthetic world (deterministic), train {} questions, held-out {} questions\n",
        train.len(),
        held_out.len()
    );

    println!("-- calibration gate (measure the signal before training RL) --");
    let gate = calibration_gate(&config, &held_out);
    for (name, mean) in [
        ("equal-split", gate.baseline_means[0]),
        ("sequential", gate.baseline_means[1]),
        ("adaptive-greedy", gate.baseline_means[2]),
    ] {
        println!("  {name:<16} held-out mean {:>9.0}", mean);
    }
    println!("  {:<16} held-out mean {:>9.0}", "oracle", gate.oracle_mean);
    println!(
        "  gate: {} (oracle / best baseline = {:.2}, need >= 1.10)\n",
        if gate.passed { "PASS" } else { "FAIL" },
        gate.margin_ratio
    );

    println!("-- training season (800 questions, minibatch every 20) --");
    let mut learner = McQLearner::new(7);
    let reports = run_season(&config, &mut learner, &train);
    let half = reports.len() / 2;
    let first_half: f64 = reports[..half]
        .iter()
        .map(|r| r.reward_milli as f64)
        .sum::<f64>()
        / half as f64;
    let second_half: f64 = reports[half..]
        .iter()
        .map(|r| r.reward_milli as f64)
        .sum::<f64>()
        / (reports.len() - half) as f64;
    println!(
        "  season mean {:>9.0} (first half {:>9.0} -> second half {:>9.0})",
        (first_half + second_half) / 2.0,
        first_half,
        second_half
    );
    println!("  q updates: {}\n", learner.updates);

    println!("-- held-out evaluation (unseen budgets 60k/140k) --");
    learner.set_eval(true);
    let learner_mean = evaluate(&config, &mut learner, &held_out);
    for (name, mut policy) in [
        (
            "equal-split",
            Box::new(EqualSplitPolicy::new()) as Box<dyn Policy>,
        ),
        ("sequential", Box::new(SequentialPolicy::new())),
        ("adaptive-greedy", Box::new(AdaptiveGreedyPolicy::new())),
    ] {
        println!(
            "  {name:<16} {:>9.0}",
            evaluate(&config, policy.as_mut(), &held_out)
        );
    }
    println!("  {:<16} {:>9.0}", "mc-q-learner", learner_mean);
    println!("  {:<16} {:>9.0}", "oracle", gate.oracle_mean);
    println!(
        "\n  learner / oracle = {:.2}",
        learner_mean / gate.oracle_mean
    );
    println!(
        "  verdict: learner >= best baseline: {}",
        learner_mean >= gate.best_baseline_mean
    );
    println!("\n(real-bench criterion: synthetic success alone is not a pass —");
    println!(" the frozen real bench is evaluated separately.)");
}
