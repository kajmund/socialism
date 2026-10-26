//! SWE Gym v2 step 6 — the frozen real legal bench (replay, offline).
//! Runs the synthetic-trained learner and the real baselines against the
//! five frozen questions and reports the criterion-5 verdict honestly.
//!
//! Run with: cargo run --example v2_real

use swe_gym::agent::{McQLearner, Policy};
use swe_gym::env::default_config;
use swe_gym::real::{
    evaluate_real, load_real_bench, run_episode_real, RealAdaptivePolicy, RealEnv,
    RealEqualSplitPolicy, RealSequentialPolicy, REAL_BASE_REWARD_MILLI,
};
use swe_gym::train::{default_question_sets, run_season};

/// v1's measured scan counts on the same bench (docs/SWE_Sweycoins_resultat.md),
/// as context rows: arm A sequential, arm H two-phase, C* oracle.
const V1_SCANS: [(&str, u64, u64, u64); 5] = [
    ("auto-renewal", 568, 38, 20),
    ("notice-period", 320, 26, 13),
    ("liability-cap", 525, 47, 34),
    ("confidentiality", 179, 18, 13),
    ("liability-secrecy-carveout", 244, 16, 7),
];

fn main() {
    println!("== SWE Gym v2 step 6 — frozen real bench (replay, offline) ==");
    println!(
        "data: 2019 JEV fixtures, 5 golden questions, budget {} coins/question\n",
        swe_gym::real::REAL_BUDGET_PER_QUESTION_MILLI / 1_000
    );

    let config = default_config();
    let (train, _) = default_question_sets();
    let mut learner = McQLearner::new(7);
    run_season(&config, &mut learner, &train);
    learner.set_eval(true);

    let questions = load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures")
        .expect("real bench loads");

    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let learner_mean = evaluate_real(&mut env, &mut learner, &questions);
    let equal_mean = evaluate_real(&mut env, &mut RealEqualSplitPolicy::new(), &questions);
    let seq_mean = evaluate_real(&mut env, &mut RealSequentialPolicy::new(0), &questions);
    let adapt_mean = evaluate_real(&mut env, &mut RealAdaptivePolicy::new(), &questions);

    println!("-- held-out = the 5 frozen real questions (mean net, milli) --");
    println!("  real-equal-split    {:>9.0}", equal_mean);
    println!("  real-sequential     {:>9.0}", seq_mean);
    println!("  real-adaptive       {:>9.0}", adapt_mean);
    println!("  mc-q-learner        {:>9.0}", learner_mean);
    println!();
    println!(
        "  criterion 5 verdict: learner >= equal-split: {}",
        learner_mean >= equal_mean
    );
    println!();

    println!("-- per question: learner vs best real baseline (adaptive) --");
    for q in &questions {
        let rl = run_episode_real(&mut env, &mut learner, q, 0);
        let learner_found = env.found_count();
        let mut a = RealAdaptivePolicy::new();
        let ra = run_episode_real(&mut env, &mut a, q, 0);
        let v1 = V1_SCANS.iter().find(|(id, _, _, _)| *id == q.id).unwrap();
        println!(
            "  {:<26} learner {:>8} (spent {:>6}, {}/{})   adaptive {:>8} (spent {:>6})   v1: A {} H {} C* {} scans",
            q.id,
            rl.reward_milli,
            rl.spent_milli,
            learner_found,
            q.required,
            ra.reward_milli,
            ra.spent_milli,
            v1.1,
            v1.2,
            v1.3,
        );
    }
    println!();
    println!("(synthetic success alone was never a pass; the real bench is the");
    println!(" final judge. See docs/SWE_Sweycoins_v2.md 11.2 for the verdict.)");
}
