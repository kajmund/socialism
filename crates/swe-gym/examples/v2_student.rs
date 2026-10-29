//! Teacher-student POC (docs/SWE_Sweycoins_v2.md 16): the mandatory
//! leave-one-question-out gate — can the behavior-cloning student
//! imitate the adaptive-pipeline teacher on a question it never saw?
//!
//! Run with: cargo run --example v2_student

use swe_gym::dataset::load_dataset;
use swe_gym::real::{
    load_real_bench, run_episode_real, RealEnv, RealPipelinePolicy, REAL_BASE_REWARD_MILLI,
};
use swe_gym::student::{leave_one_out_gate, teacher_pairs, StudentPolicy};

fn main() {
    let source = std::fs::read_to_string("benchmarks/real_trajectories_v1.json").unwrap();
    let trajectories = load_dataset(&source).unwrap();

    println!("== teacher-student POC: leave-one-question-out gate ==");
    println!("teacher: real-pipeline-adaptive (observation-deterministic)");
    println!("student: multinomial logistic regression, 11 facit-free features\n");

    let agreements = leave_one_out_gate(&trajectories);
    for (i, a) in agreements.iter().enumerate() {
        println!("  fold {i} (hold out question {i}): agreement {:.3}", a);
    }
    let mean = agreements.iter().sum::<f64>() / agreements.len() as f64;
    println!("  mean: {mean:.3}  (gate: every fold >= 0.90, mean >= 0.95)\n");
    println!(
        "  GATE: {}",
        if agreements.iter().all(|a| *a >= 0.90) && mean >= 0.95 {
            "PASS"
        } else {
            "FAIL"
        }
    );

    // Roll-out demonstration: train on four questions, drive the real
    // env on the fifth, compare with the teacher.
    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();
    let held = "notice-period";
    let train: Vec<_> = trajectories
        .iter()
        .filter(|t| t.question_id != held)
        .cloned()
        .collect();
    let student = StudentPolicy::train(&teacher_pairs(&train), 1_000, 0.5);
    println!("\n-- roll-out on the held-out question ({held}) --");
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    for budget in [100_000u64, 200_000, 300_000] {
        let q = questions.iter().find(|q| q.id == held).unwrap();
        let mut q = q.clone();
        q.budget_milli = budget;
        let mut teacher = RealPipelinePolicy::new();
        let teacher_net = run_episode_real(&mut env, &mut teacher, &q, 0).reward_milli;
        let mut student_policy = student.clone();
        let student_net = run_episode_real(&mut env, &mut student_policy, &q, 0).reward_milli;
        println!(
            "  budget {budget:>6}: teacher {teacher_net:>7}   student {student_net:>7}   {}",
            if student_net == teacher_net {
                "identical"
            } else {
                "differs"
            }
        );
    }
    println!("\n(next per the plan: controlled exploration on top of the student,");
    println!(" with terminal quality as the credit signal — only after this gate.)");
}
