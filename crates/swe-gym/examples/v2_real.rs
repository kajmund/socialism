//! SWE Gym v2 — the real two-capability benchmark (docs/SWE_Sweycoins_v2.md
//! 14): retrieval (A, pool extension) + JEV (B, frozen 2019 answers) over
//! the common observation interface. Frozen and reproducible; quality is
//! revealed only at episode end.
//!
//! Run with: cargo run --example v2_real

use swe_gym::real::{
    evaluate_real, load_real_bench, run_episode_real, RealEnv, RealEqualSplitPolicy,
    RealPipelinePolicy, REAL_BASE_REWARD_MILLI,
};

fn main() {
    println!("== SWE Gym v2 — real benchmark (frozen, offline) ==");
    println!(
        "capabilities: A=retrieval ({} milli/chunk, no direct evidence)  B=JEV ({} milli/call, 2019 fixtures)\n",
        swe_gym::real::LOOKUP_MILLI,
        swe_gym::real::SCAN_MILLI
    );

    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);

    let mut learner = swe_gym::train::train_benchmark_learner(7);
    let learner_mean = evaluate_real(&mut env, &mut learner, &questions);
    let pipeline_mean = evaluate_real(&mut env, &mut RealPipelinePolicy::new(), &questions);
    let equal_mean = evaluate_real(&mut env, &mut RealEqualSplitPolicy::new(), &questions);

    println!("-- the five frozen golden questions (mean net, milli) --");
    println!("  real-equal-split        {:>9.0}", equal_mean);
    println!("  real-pipeline-adaptive  {:>9.0}", pipeline_mean);
    println!("  mc-q-learner            {:>9.0}", learner_mean);
    println!(
        "\n  verdict: learner vs strong baseline: {}",
        if learner_mean >= pipeline_mean {
            ">= (beats it)"
        } else {
            "< (regresses)"
        }
    );

    println!("\n-- per question (learner / pipeline) --");
    for q in &questions {
        let rl = run_episode_real(&mut env, &mut learner, q, 0);
        let lf = env.found_count();
        let mut p = RealPipelinePolicy::new();
        let rp = run_episode_real(&mut env, &mut p, q, 0);
        let pf = env.found_count();
        println!(
            "  {:<26} learner {:>8} (spent {:>6}, {}/{})   pipeline {:>8} (spent {:>6}, {}/{})",
            q.id,
            rl.reward_milli,
            rl.spent_milli,
            lf,
            q.required,
            rp.reward_milli,
            rp.spent_milli,
            pf,
            q.required
        );
    }
    println!("\n(state-geometry verdict and next steps: docs/SWE_Sweycoins_v2.md 14.)");
}
