//! Collect the teacher dataset (docs/SWE_Sweycoins_v2.md 15): the
//! adaptive pipeline's decision sequences over the frozen real bench at
//! three budget levels — question features come with each step's
//! observation; the facit appears only in the terminal quality field.
//! Offline, deterministic, frozen afterwards.
//!
//! Run with: cargo run --example v2_collect

use swe_gym::agent::Policy;
use swe_gym::dataset::{dataset_to_json, record_episode};
use swe_gym::real::{
    load_real_bench, RealEnv, RealEqualSplitPolicy, RealPipelinePolicy, REAL_BASE_REWARD_MILLI,
};

fn main() {
    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let mut trajectories = Vec::new();
    for budget in [100_000u64, 200_000, 300_000] {
        let mut policies: Vec<(String, u64, Box<dyn Policy>)> = vec![
            (
                "real-pipeline-adaptive".into(),
                0,
                Box::new(RealPipelinePolicy::new()),
            ),
            (
                "real-equal-split".into(),
                0,
                Box::new(RealEqualSplitPolicy::new()),
            ),
            (
                "mc-q-learner-synthetic".into(),
                7,
                Box::new(swe_gym::train::train_benchmark_learner(7)),
            ),
        ];
        for (i, q) in questions.iter().enumerate() {
            let mut q_with_budget = q.clone();
            q_with_budget.budget_milli = budget;
            for (name, seed, policy) in policies.iter_mut() {
                trajectories.push(record_episode(
                    &mut env,
                    policy.as_mut(),
                    &q_with_budget,
                    i as u64,
                    name,
                    *seed,
                ));
            }
        }
    }
    let json = dataset_to_json(&trajectories);
    let path = "benchmarks/real_trajectories_v1.json";
    std::fs::write(path, json).expect("write dataset");
    println!(
        "wrote {path}: {} trajectories (5 questions x 3 budgets)",
        trajectories.len()
    );
    for t in &trajectories {
        println!(
            "  {:<26} b={:>6} steps={:>3} quality={:.2} cost={:>7} net={:>7}",
            t.question_id,
            t.budget_milli,
            t.steps.len(),
            t.terminal_quality,
            t.total_cost_milli,
            t.total_reward_milli
        );
    }
}
