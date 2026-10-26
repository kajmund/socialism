//! Teacher-student POC (docs/SWE_Sweycoins_v2.md 16): behavior cloning
//! from the adaptive pipeline with leave-one-question-out as the
//! mandatory first gate. The teacher is observation-deterministic by
//! construction, so a perfect student is achievable in principle — the
//! gate measures whether the student generalizes to unseen questions.

use swe_gym::dataset::load_dataset;
use swe_gym::real::{
    evaluate_real, load_real_bench, RealEnv, RealPipelinePolicy, REAL_BASE_REWARD_MILLI,
};
use swe_gym::student::{features, leave_one_out_gate, teacher_pairs, StudentPolicy, FEATURE_COUNT};

#[test]
fn student_features_are_facit_free() {
    // The feature vector is built from the observation interface only —
    // no answer key, no terminal quality. Structural pin: the feature
    // count is fixed and every feature comes from `Observation`.
    assert_eq!(FEATURE_COUNT, 11);
    let obs = swe_gym::env::Observation {
        question_id: "x".into(),
        qtype: 1,
        remaining_milli: 100_000,
        bracket: 2,
        tiers: [0, 0, 0],
        found: 7,
        new_evidence: 1,
        contradictions: 0,
        recent_hit_rate_bp: 3_500,
        last_score_bp: 9_000,
        pool_scanned: 20,
        pool_total: 400,
        pool_extension_yielded: 1,
        zero_hit_streak: 2,
        statuses: [swe_gym::env::Status::Active; 3],
        spent_milli: [1_000, 20_000, 0],
        steps: 5,
    };
    let f = features(&obs);
    assert_eq!(f.len(), FEATURE_COUNT);
    assert!(f.iter().all(|v| v.is_finite()));
}

#[test]
fn leave_one_question_out_gate_passes() {
    // The mandatory first gate: train on four questions, test on the
    // fifth, five times. Every fold must reach the pre-registered
    // agreement threshold; all nine test-question trajectories (three
    // policies) stay out of training except the teacher's three.
    let source = include_str!("../benchmarks/real_trajectories_v1.json");
    let trajectories = load_dataset(source).unwrap();
    let agreements = leave_one_out_gate(&trajectories);
    assert_eq!(agreements.len(), 5);
    assert_eq!(
        agreements,
        [1.0, 1.0, 1.0, 1.0, 1.0],
        "fold agreements pinned"
    );
    for (i, a) in agreements.iter().enumerate() {
        assert!(*a >= 0.90, "fold {i}: agreement {a} below the gate");
    }
    let mean = agreements.iter().sum::<f64>() / agreements.len() as f64;
    assert!(mean >= 0.95, "mean agreement {mean}");
}

#[test]
fn student_rollout_matches_the_teacher_on_held_out_questions() {
    // 100% state-action agreement implies the student's roll-out IS the
    // teacher's roll-out on the held-out question. Verify end to end:
    // train on four questions, drive the real env on the fifth, and
    // compare the net against the teacher's recorded net.
    let source = include_str!("../benchmarks/real_trajectories_v1.json");
    let trajectories = load_dataset(source).unwrap();
    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();
    let held = "notice-period";
    let train: Vec<_> = trajectories
        .iter()
        .filter(|t| t.question_id != held)
        .cloned()
        .collect();
    let student = StudentPolicy::train(&teacher_pairs(&train), 1_000, 0.5);

    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    for budget in [100_000u64, 200_000, 300_000] {
        let q = questions.iter().find(|q| q.id == held).unwrap();
        let mut q = q.clone();
        q.budget_milli = budget;
        let mut teacher = RealPipelinePolicy::new();
        let teacher_net =
            swe_gym::real::run_episode_real(&mut env, &mut teacher, &q, 0).reward_milli;
        let mut student_policy = student.clone();
        let student_net =
            swe_gym::real::run_episode_real(&mut env, &mut student_policy, &q, 0).reward_milli;
        assert_eq!(
            student_net, teacher_net,
            "budget {budget}: student rollout {student_net} != teacher {teacher_net}"
        );
    }
    let _ = evaluate_real;
}
