//! Controlled exploration (docs/SWE_Sweycoins_v2.md 17): the student
//! tries alternative investments around the teacher, exploration happens
//! only in the training environment, and evaluation freezes the policy.
//!
//! Two exploration arms:
//! - B "enkel exploration": epsilon-greedy around the teacher, uniform
//!   random alternatives.
//! - C "riktad exploration": epsilon rises at economically decisive or
//!   uncertain states — JEV's hit rate dropping, the stall boundary,
//!   a pool extension that paid nothing, budget running low — and the
//!   alternatives are biased toward cheaper/shorter moves (finish
//!   earlier, finer JEV bets, larger pool extensions).
//!
//! Every deviation from the teacher is recorded so the report can show
//! which decisions changed and whether they paid.

use crate::agent::Policy;
use crate::dataset::{record_episode, Trajectory};
use crate::env::{Action, Observation};
use crate::real::{RealEnv, RealPipelinePolicy, RealQuestion};
use crate::student::{teacher_pairs, StudentPolicy};

/// The teacher's stall threshold (matches RealPipelinePolicy's default).
const STALL_THRESHOLD: u8 = 12;

fn next_f64(state: &mut u64) -> f64 {
    let mut x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *state = x;
    (x >> 11) as f64 / (1u64 << 53) as f64
}

/// B: epsilon-greedy around the teacher — a uniform random valid action
/// with probability epsilon, the teacher's action otherwise.
pub struct EpsilonTeacherPolicy {
    teacher: RealPipelinePolicy,
    epsilon: f64,
    rng_state: u64,
}

impl EpsilonTeacherPolicy {
    pub fn new(epsilon: f64, seed: u64) -> Self {
        Self {
            teacher: RealPipelinePolicy::new(),
            epsilon,
            rng_state: seed.max(1),
        }
    }
}

impl Policy for EpsilonTeacherPolicy {
    fn name(&self) -> &'static str {
        "explore-epsilon"
    }

    fn episode_start(&mut self, question: &crate::env::Question, question_index: u64) {
        self.teacher.episode_start(question, question_index);
        for _ in 0..(question_index % 64 + 1) {
            next_f64(&mut self.rng_state);
        }
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if next_f64(&mut self.rng_state) < self.epsilon {
            // Invests and Finish only: Pause/Stop would poison the
            // teacher's subsequent investments (they are dominated
            // no-ops, never worth exploring).
            let picks: Vec<Action> = valid
                .iter()
                .copied()
                .filter(|a| !matches!(a, Action::Pause(_) | Action::Stop(_)))
                .collect();
            let pick = (next_f64(&mut self.rng_state) * picks.len() as f64) as usize;
            return picks[pick.min(picks.len() - 1)];
        }
        self.teacher.act(obs, valid)
    }
}

/// C: directed exploration — epsilon scales with how decisive the state
/// is, and alternatives are biased toward cheaper/shorter moves.
pub struct DirectedTeacherPolicy {
    teacher: RealPipelinePolicy,
    base_epsilon: f64,
    max_epsilon: f64,
    rng_state: u64,
}

impl DirectedTeacherPolicy {
    pub fn new(base_epsilon: f64, max_epsilon: f64, seed: u64) -> Self {
        Self {
            teacher: RealPipelinePolicy::new(),
            base_epsilon,
            max_epsilon,
            rng_state: seed.max(1),
        }
    }

    /// The directed exploration rate at a state: base plus bonuses for
    /// the economically decisive signals (docs 17).
    pub fn rate(&self, obs: &Observation) -> f64 {
        let mut e = self.base_epsilon;
        if obs.remaining_milli < 30_000 {
            e += 0.10; // budget running low
        }
        if obs.recent_hit_rate_bp > 0 && obs.recent_hit_rate_bp <= 3_000 {
            e += 0.10; // JEV's hit rate dropping
        }
        let d = (obs.zero_hit_streak as i32 - STALL_THRESHOLD as i32).abs();
        if d <= 4 {
            e += 0.15; // the stall decision is close
        }
        if obs.pool_extension_yielded == 0 && obs.pool_scanned > 0 {
            e += 0.10; // the last extension paid nothing
        }
        e.min(self.max_epsilon)
    }

    /// Alternatives biased toward cheaper/shorter moves: finish earlier
    /// and finer JEV bets first, then larger pool extensions.
    fn alternative(&mut self, valid: &[Action]) -> Action {
        let mut candidates: Vec<Action> = vec![
            Action::Finish,
            Action::Invest(1, 1_000),
            Action::Invest(0, 5_000),
            Action::Invest(1, 10_000),
        ];
        candidates.retain(|a| valid.contains(a));
        if candidates.is_empty() {
            let picks: Vec<Action> = valid
                .iter()
                .copied()
                .filter(|a| !matches!(a, Action::Pause(_) | Action::Stop(_)))
                .collect();
            let pick = (next_f64(&mut self.rng_state) * picks.len() as f64) as usize;
            return picks[pick.min(picks.len() - 1)];
        }
        // Weighted: 40% finish, 25% fine JEV, 20% larger extension, 15% big JEV.
        let r = next_f64(&mut self.rng_state);
        let weights = [0.40, 0.25, 0.20, 0.15];
        let mut acc = 0.0;
        for (w, c) in weights.iter().zip(candidates.iter()) {
            acc += w;
            if r < acc {
                return *c;
            }
        }
        candidates[0]
    }
}

impl Policy for DirectedTeacherPolicy {
    fn name(&self) -> &'static str {
        "explore-directed"
    }

    fn episode_start(&mut self, question: &crate::env::Question, question_index: u64) {
        self.teacher.episode_start(question, question_index);
        for _ in 0..(question_index % 64 + 1) {
            next_f64(&mut self.rng_state);
        }
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if next_f64(&mut self.rng_state) < self.rate(obs) {
            self.alternative(valid)
        } else {
            self.teacher.act(obs, valid)
        }
    }
}

/// Run exploration episodes in the training environment (frozen replay)
/// and record every trajectory, deviations included by construction.
pub fn run_exploration(
    env: &mut RealEnv,
    _policy: &mut dyn Policy,
    questions: &[RealQuestion],
    episodes_per_question: usize,
    policy_name: &str,
    seed: u64,
) -> Vec<Trajectory> {
    let mut out = Vec::new();
    for (i, q) in questions.iter().enumerate() {
        for e in 0..episodes_per_question {
            let mut episode_policy = episode_policy(policy_name, seed + e as u64);
            out.push(record_episode(
                env,
                episode_policy.as_mut(),
                q,
                i as u64,
                policy_name,
                seed + e as u64,
            ));
        }
    }
    out
}

fn episode_policy(name: &str, seed: u64) -> Box<dyn Policy> {
    match name {
        "explore-epsilon" => Box::new(EpsilonTeacherPolicy::new(0.10, seed)),
        _ => Box::new(DirectedTeacherPolicy::new(0.05, 0.50, seed)),
    }
}

/// Reward- and quality-filtered behavior cloning: keep only the
/// exploration episodes that beat the teacher's net AND match its
/// verified quality on the same (question, budget) — the facit is used
/// at training time for credit, exactly as allowed, and never enters
/// the policy. (Measured: filtering by net alone let cheap-but-shallow
/// episodes through and degraded coverage.)
pub fn improved_student(
    teacher_trajectories: &[Trajectory],
    exploration: &[Trajectory],
) -> StudentPolicy {
    let mut teacher_by_key: std::collections::HashMap<(String, u64), (f64, f64)> =
        std::collections::HashMap::new();
    for t in teacher_trajectories {
        if t.policy != "real-pipeline-adaptive" {
            continue;
        }
        teacher_by_key.insert(
            (t.question_id.clone(), t.budget_milli),
            (t.total_reward_milli as f64, t.terminal_quality),
        );
    }

    let mut pairs = teacher_pairs(teacher_trajectories);
    let mut kept = 0usize;
    for t in exploration {
        let Some(&(teacher_net, teacher_quality)) =
            teacher_by_key.get(&(t.question_id.clone(), t.budget_milli))
        else {
            continue;
        };
        if t.total_reward_milli as f64 > teacher_net && t.terminal_quality >= teacher_quality {
            kept += 1;
            for step in &t.steps {
                pairs.push((
                    crate::student::features(&step.obs).to_vec(),
                    crate::student::class_of(step.action),
                ));
            }
        }
    }
    // If no exploration episode improved on the teacher, the student is
    // pure behavior cloning — the honest fallback.
    let _ = kept;
    StudentPolicy::train(&pairs, 200, 0.5)
}

/// One evaluated run: net, quality and cost of a frozen policy on one
/// question, plus the deviations from the teacher's decisions.
pub struct EvalRun {
    pub net: i64,
    pub quality: f64,
    pub cost: u64,
    pub deviations: usize,
    pub deviation_log: Vec<String>,
}

pub fn eval_frozen(env: &mut RealEnv, policy: &mut dyn Policy, question: &RealQuestion) -> EvalRun {
    env.reset(question).expect("valid question");
    policy.episode_start(
        &crate::env::Question {
            id: question.id.clone(),
            qtype: question.qtype,
            budget_milli: question.budget_milli,
        },
        0,
    );
    let mut teacher = RealPipelinePolicy::new();
    teacher.episode_start(
        &crate::env::Question {
            id: question.id.clone(),
            qtype: question.qtype,
            budget_milli: question.budget_milli,
        },
        0,
    );
    let mut deviations = 0usize;
    let mut log = Vec::new();
    let mut total = 0i64;
    loop {
        let obs = env.observation().clone();
        let valid = env.valid_actions();
        let teacher_action = teacher.act(&obs, &valid);
        let action = policy.act(&obs, &valid);
        let (_o, info) = env.step(action).expect("valid action");
        total += info.reward_milli;
        policy.on_step(info.reward_milli);
        if action != teacher_action {
            deviations += 1;
            log.push(format!(
                "rem={} streak={} hitrate={} yield={} teacher={:?} chose={:?}",
                obs.remaining_milli,
                obs.zero_hit_streak,
                obs.recent_hit_rate_bp,
                obs.pool_extension_yielded,
                teacher_action,
                action
            ));
        }
        if info.done {
            break;
        }
    }
    EvalRun {
        net: total,
        quality: env.terminal_quality(),
        cost: env.observation().spent_milli.iter().sum(),
        deviations,
        deviation_log: log,
    }
}
