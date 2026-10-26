//! SWE Gym v2 — the real training dataset (docs/SWE_Sweycoins_v2.md 15):
//! recorded decision sequences over the frozen bench. Facit appears only
//! in the terminal quality field; the dataset replays deterministically.

use swe_gym::agent::Policy;
use swe_gym::dataset::{dataset_to_json, load_dataset, record_episode, DATASET_VERSION};
use swe_gym::real::{load_real_bench, RealEnv, RealPipelinePolicy, REAL_BASE_REWARD_MILLI};

#[test]
fn dataset_round_trips_losslessly() {
    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    let mut policy = RealPipelinePolicy::new();
    let trajectory = record_episode(&mut env, &mut policy, &questions[0], 0, "pipeline", 0);
    let json = dataset_to_json(&[trajectory.clone()]);
    let loaded = load_dataset(&json).unwrap();
    assert_eq!(loaded.len(), 1);
    assert_eq!(loaded[0], trajectory);
}

#[test]
fn recorded_trajectory_replays_to_the_same_terminal_quality() {
    // A recorded trajectory is experience data: replaying its exact
    // actions through the frozen env must reproduce the recorded
    // terminal quality — the reproducibility guarantee of the dataset.
    let source = include_str!("../benchmarks/real_trajectories_v1.json");
    let trajectories = load_dataset(source).unwrap();
    let questions =
        load_real_bench("benchmarks/bench_real_v2.json", "benchmarks/real_fixtures").unwrap();
    let mut env = RealEnv::new(REAL_BASE_REWARD_MILLI);
    for t in trajectories.iter().take(6) {
        let q = questions.iter().find(|q| q.id == t.question_id).unwrap();
        let mut q = q.clone();
        q.budget_milli = t.budget_milli;
        env.reset(&q).unwrap();
        for step in &t.steps {
            let (_obs, info) = env.step(step.action).unwrap();
            if info.done {
                break;
            }
        }
        assert_eq!(
            env.terminal_quality(),
            t.terminal_quality,
            "{}: replay quality drifted",
            t.question_id
        );
    }
}

#[test]
fn collected_dataset_is_frozen_and_mixed_quality() {
    let source = include_str!("../benchmarks/real_trajectories_v1.json");
    let json = swe_native::parse_json_str(source).unwrap();
    let version = json
        .get("version")
        .and_then(swe_native::Json::as_number)
        .and_then(|n| n.as_u64())
        .unwrap();
    assert_eq!(version, DATASET_VERSION);

    let trajectories = load_dataset(source).unwrap();
    assert_eq!(
        trajectories.len(),
        45,
        "5 questions x 3 budgets x 3 policies"
    );
    for t in &trajectories {
        assert!(!t.steps.is_empty());
        assert!((0.0..=1.0).contains(&t.terminal_quality));
        assert_eq!(
            t.total_reward_milli,
            t.steps.iter().map(|s| s.reward_milli).sum::<i64>(),
            "{}: reward stream must sum to the total",
            t.question_id
        );
    }
    // The mixed-quality composition is the point: teacher demonstrations
    // plus the synthetic learner's real-world mistakes, labeled by
    // terminal quality — the input for behavior cloning / offline RL.
    let sum = |policy: &str| -> i64 {
        trajectories
            .iter()
            .filter(|t| t.policy == policy)
            .map(|t| t.total_reward_milli)
            .sum()
    };
    // Pinned as integer sums (15 trajectories per policy).
    assert_eq!(sum("real-pipeline-adaptive"), PIPELINE_SUM_PIN);
    assert_eq!(sum("real-equal-split"), EQUAL_SUM_PIN);
    assert_eq!(sum("mc-q-learner-synthetic"), LEARNER_SUM_PIN);
    assert!(
        sum("real-pipeline-adaptive") > sum("mc-q-learner-synthetic"),
        "the dataset must contain the teacher's advantage"
    );
}

const PIPELINE_SUM_PIN: i64 = 882_693;
const EQUAL_SUM_PIN: i64 = 368_000;
const LEARNER_SUM_PIN: i64 = -318_000;
