//! Training and evaluation harness for the v2 budget-manager gym:
//! question sets (train vs held-out), the episode loop, the training
//! season, policy evaluation and the calibration gate.
//!
//! Facit isolation (crate non-negotiable 3): the held-out set is never
//! used for training; the oracle only ever reports the ceiling. Synthetic
//! and real numbers are never mixed (non-negotiable 1).

use crate::agent::Policy;
use crate::env::{EnvConfig, Question, SweEnv, SyntheticEnv};

/// Training set: every type x 200 fresh ids at 100 coins. Spec 7's
/// "example" season of 200 questions measured too small for the tabular
/// arm (sparse MC credit); the season size stays configurable. Held-out
/// set: every type at 60 and 140 coins — unseen budgets, so
/// generalization is actually tested.
pub fn default_question_sets() -> (Vec<Question>, Vec<Question>) {
    let mut train = Vec::new();
    for qtype in 0..4u8 {
        for i in 0..200u32 {
            train.push(Question {
                id: format!("train-t{qtype}-{i}"),
                qtype,
                budget_milli: 100_000,
            });
        }
    }
    let mut held_out = Vec::new();
    for qtype in 0..4u8 {
        for budget in [60_000, 140_000] {
            held_out.push(Question {
                id: format!("held-t{qtype}-b{budget}"),
                qtype,
                budget_milli: budget,
            });
        }
    }
    (train, held_out)
}

#[derive(Clone, Debug)]
pub struct EpisodeReport {
    pub question_id: String,
    pub qtype: u8,
    pub steps: u32,
    pub reward_milli: i64,
    pub spent_milli: u64,
    pub reason: String,
}

/// Run one episode with a fresh env (so the ledger is per question) and
/// return the report. Deterministic given the policy. The reported reward
/// is the net return (sum of the env's per-step rewards).
pub fn run_episode(
    config: &EnvConfig,
    policy: &mut dyn Policy,
    question: &Question,
    question_index: u64,
) -> EpisodeReport {
    let mut env = SyntheticEnv::new(config.clone());
    env.reset(question).expect("valid question");
    policy.episode_start(question, question_index);
    let mut total_reward: i64 = 0;
    loop {
        let valid = env.valid_actions();
        let action = policy.act(env.observation(), &valid);
        let (_obs, info) = env.step(action).expect("policy picked a valid action");
        total_reward += info.reward_milli;
        policy.on_step(info.reward_milli);
        if info.done {
            policy.episode_end(total_reward);
            let obs = env.observation();
            return EpisodeReport {
                question_id: question.id.clone(),
                qtype: question.qtype,
                steps: obs.steps,
                reward_milli: total_reward,
                spent_milli: obs.spent_milli.iter().sum(),
                reason: info.reason,
            };
        }
    }
}

/// Mean reward over a question set. Baselines are deterministic; a
/// learner must be in eval mode.
pub fn evaluate(config: &EnvConfig, policy: &mut dyn Policy, questions: &[Question]) -> f64 {
    let mut total = 0.0;
    for (i, q) in questions.iter().enumerate() {
        total += run_episode(config, policy, q, i as u64).reward_milli as f64;
    }
    total / questions.len() as f64
}

/// One training season: run the questions in order, let the learner
/// update (minibatched internally), and report the running mean.
pub fn run_season(
    config: &EnvConfig,
    learner: &mut dyn Policy,
    questions: &[Question],
) -> Vec<EpisodeReport> {
    let mut reports = Vec::with_capacity(questions.len());
    for (i, q) in questions.iter().enumerate() {
        reports.push(run_episode(config, learner, q, i as u64));
    }
    reports
}

/// Results of the calibration gate (docs/SWE_Sweycoins_v2.md 9, criterion 1).
#[derive(Clone, Debug)]
pub struct GateReport {
    pub oracle_mean: f64,
    pub baseline_means: [f64; 3],
    pub best_baseline_mean: f64,
    pub margin_ratio: f64,
    pub passed: bool,
}

/// Measure the signal before training RL (v1's core lesson): the oracle
/// must beat the best simple baseline by a pre-registered margin on the
/// held-out set, otherwise the synthetic world has nothing learnable.
pub fn calibration_gate(config: &EnvConfig, held_out: &[Question]) -> GateReport {
    use crate::agent::{AdaptiveGreedyPolicy, EqualSplitPolicy, SequentialPolicy};
    use crate::oracle::oracle_value;

    let mut oracle_total = 0.0;
    for q in held_out {
        oracle_total += oracle_value(config, q.qtype, q.budget_milli) as f64;
    }
    let oracle_mean = oracle_total / held_out.len() as f64;

    let baseline_means = [
        evaluate(config, &mut EqualSplitPolicy::new(), held_out),
        evaluate(config, &mut SequentialPolicy::new(), held_out),
        evaluate(config, &mut AdaptiveGreedyPolicy::new(), held_out),
    ];
    let best_baseline_mean = baseline_means.iter().cloned().fold(f64::MIN, f64::max);
    let margin_ratio = if best_baseline_mean > 0.0 {
        oracle_mean / best_baseline_mean
    } else {
        f64::INFINITY
    };
    GateReport {
        oracle_mean,
        baseline_means,
        best_baseline_mean,
        margin_ratio,
        passed: margin_ratio >= 1.10,
    }
}
