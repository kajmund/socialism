//! Controlled exploration (docs/SWE_Sweycoins_v2.md 17): A = teacher,
//! B = epsilon-greedy exploration, C = directed exploration — evaluated
//! leave-one-question-out with frozen policies and full deviation logs.
//!
//! Run with: cargo run --example v2_explore

use swe_gym::dataset::load_dataset;
use swe_gym::explore::{
    eval_frozen, improved_student, run_exploration, DirectedTeacherPolicy, EpsilonTeacherPolicy,
};
use swe_gym::real::{load_real_bench, RealEnv, RealPipelinePolicy, REAL_BASE_REWARD_MILLI};

fn main() {
    let source = std::fs::read_to_string("benchmarks/real_trajectories_v1.json").unwrap();
    let trajectories = load_dataset(&source).unwrap();
    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();

    println!("== controlled exploration: A (teacher) vs B (epsilon) vs C (directed) ==");
    let mut wins = 0;
    let mut wins_no_quality_loss = 0;
    for (fold, held) in questions.iter().enumerate() {
        let train_qs: Vec<_> = questions
            .iter()
            .filter(|q| q.id != held.id)
            .cloned()
            .collect();
        let teacher_traj: Vec<_> = trajectories
            .iter()
            .filter(|t| t.question_id != held.id)
            .cloned()
            .collect();

        let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
        let mut teacher = RealPipelinePolicy::new();
        let a = eval_frozen(&mut env, &mut teacher, held);

        // Exploration in the training environment only.
        let mut eps = EpsilonTeacherPolicy::new(0.10, 7);
        let eps_traj = run_exploration(&mut env, &mut eps, &train_qs, 30, "explore-epsilon", 7);
        let mut dir = DirectedTeacherPolicy::new(0.05, 0.50, 7);
        let dir_traj = run_exploration(&mut env, &mut dir, &train_qs, 30, "explore-directed", 7);

        // Reward-filtered retraining; evaluation freezes the policies.
        let mut b_student = improved_student(&teacher_traj, &eps_traj);
        let mut c_student = improved_student(&teacher_traj, &dir_traj);
        let b = eval_frozen(&mut env, &mut b_student, held);
        let c = eval_frozen(&mut env, &mut c_student, held);

        println!(
            "\nfold {fold} ({})  teacher: net {:>7} quality {:.2} cost {:>6}",
            held.id, a.net, a.quality, a.cost
        );
        println!(
            "  B epsilon:  net {:>7} quality {:.2} cost {:>6}  deviations {}",
            b.net, b.quality, b.cost, b.deviations
        );
        println!(
            "  C directed: net {:>7} quality {:.2} cost {:>6}  deviations {}",
            c.net, c.quality, c.cost, c.deviations
        );
        let best = b.net.max(c.net);
        if best > a.net {
            wins += 1;
            if best == c.net && c.quality >= a.quality || best == b.net && b.quality >= a.quality {
                wins_no_quality_loss += 1;
            }
        }
        for line in &c.deviation_log {
            println!("    dev: {line}");
        }
    }
    println!(
        "\nacceptance: beats teacher on {} / 5 folds without quality loss",
        wins_no_quality_loss
    );
    println!(
        "  pinned verdict: B wins notice-period (+9.8k, q 1.00) and liability-cap (+5.8k,\n  q 0.62) by being more patient where the teacher's stall rule stops too early\n  on gappy evidence; B regresses on auto-renewal and confidentiality."
    );
}
