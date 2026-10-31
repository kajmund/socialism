//! TD(0) Sarsa over the scan checkpoint chain — the proper sequential-RL
//! step. Replaces the myopic credit of the tabular bandit with a
//! bootstrapped value: Q(s, continue) propagates the value of the rest of
//! the episode, so the policy can represent "keep scanning now because the
//! scans make escalation work later".
//!
//! On-policy Sarsa with an offline backward pass over the recorded decision
//! chain per episode: the terminal escalate (or the forced escalation after
//! scan exhaustion) carries the run's final reward, and Q values propagate
//! backward with discount gamma. Facit-free, deterministic per seed.

use crate::bandit::{reward_for, scan_context, scan_state_key};
use crate::benchmark::run_arm;
use swe_budget::Amount;
use crate::strategy::ScanDecision;
use crate::strategy::{
    rank_unresolved_by_score, BranchPlan, Continuation, Observations, ProviderKind, Question,
    QuestionView, ScanState, Strategy, Tariffs,
};
use std::collections::HashMap;

/// Continue may be overridden only after this many samples in a state —
/// the same conservative guard as the tabular bandit: one lucky sample must
/// not lock in an early stop.
pub const MIN_SAMPLES: f64 = 5.0;

#[derive(Clone, Debug)]
pub struct TdPolicy {
    /// state key → [Q(continue), Q(escalate)] plus [count_continue, count_escalate].
    q: HashMap<u64, [f64; 2]>,
    counts: HashMap<u64, [f64; 2]>,
    epsilon: f64,
    alpha: f64,
    gamma: f64,
    rng_state: u64,
    updates: u64,
}

impl TdPolicy {
    /// Optimistic Q init: both actions look valuable until sampled, so the
    /// epsilon-greedy loop tries both.
    pub fn new(seed: u64, epsilon: f64, alpha: f64, gamma: f64) -> Self {
        Self {
            q: HashMap::new(),
            counts: HashMap::new(),
            epsilon,
            alpha,
            gamma,
            rng_state: seed.max(1),
            updates: 0,
        }
    }

    fn next_f64(&mut self) -> f64 {
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        (x >> 11) as f64 / (1u64 << 53) as f64
    }

    pub fn tick_rng(&mut self, steps: u64) {
        for _ in 0..steps {
            self.next_f64();
        }
    }

    pub fn q_value(&self, state: u64, action: usize) -> f64 {
        self.q
            .get(&state)
            .map(|values| values[action])
            .unwrap_or(5.0)
    }

    pub fn count(&self, state: u64, action: usize) -> f64 {
        self.counts
            .get(&state)
            .map(|counts| counts[action])
            .unwrap_or(0.0)
    }

    fn increment(&mut self, state: u64, action: usize, target: f64) {
        let value = self.q.entry(state).or_insert([5.0; 2]);
        let counts = self.counts.entry(state).or_insert([0.0; 2]);
        value[action] += self.alpha * (target - value[action]);
        counts[action] += 1.0;
        self.updates += 1;
    }

    /// One Sarsa update for a recorded decision.
    ///
    /// `next`: the state and action of the following decision, if any. The
    /// terminal decision — an escalate, or the final continue whose next
    /// state is the forced exhaustion escalation — receives the run's final
    /// reward directly.
    pub fn update_sarsa(
        &mut self,
        state: u64,
        action: usize,
        next: Option<(u64, usize)>,
        final_reward: f64,
    ) {
        let target = match next {
            Some((next_state, next_action)) => self.gamma * self.q_value(next_state, next_action),
            None => final_reward,
        };
        self.increment(state, action, target);
    }

    /// Epsilon-greedy during training.
    pub fn decide(&mut self, state: u64) -> usize {
        if self.next_f64() < self.epsilon {
            return (self.next_f64() * 2.0) as usize;
        }
        self.greedy(state)
    }

    /// Greedy, deterministic; ties continue; escalate needs MIN_SAMPLES.
    pub fn greedy(&self, state: u64) -> usize {
        if self.count(state, 1) < MIN_SAMPLES {
            return 0;
        }
        if self.q_value(state, 1) > self.q_value(state, 0) {
            1
        } else {
            0
        }
    }

    pub fn set_epsilon(&mut self, epsilon: f64) {
        self.epsilon = epsilon;
    }

    pub fn updates(&self) -> u64 {
        self.updates
    }
}

/// Arm G: TD over the scan checkpoints. Same plan and ranking as C/E; the
/// per-step decision comes from the learned Q values.
pub struct TdSequentialStrategy {
    policy: TdPolicy,
    decisions: Vec<(u64, ScanDecision)>,
}

impl TdSequentialStrategy {
    pub fn new(policy: TdPolicy) -> Self {
        Self {
            policy,
            decisions: Vec::new(),
        }
    }

    pub fn take_decisions(&mut self) -> Vec<(u64, ScanDecision)> {
        std::mem::take(&mut self.decisions)
    }
}

impl Strategy for TdSequentialStrategy {
    fn name(&self) -> &'static str {
        "G TD (Sarsa)"
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        tariffs: &Tariffs,
    ) -> Vec<BranchPlan> {
        let chunks = if view.scan_order.is_empty() {
            view.chunks.clone()
        } else {
            view.scan_order.clone()
        };
        let scan_cost = tariffs.scan_milli.saturating_mul(chunks.len() as Amount);
        let scan_budget = scan_cost.min(total_budget_milli);
        vec![
            BranchPlan {
                account: "g-scan".into(),
                provider: ProviderKind::Scan,
                chunks,
                start_budget_milli: scan_budget,
            },
            BranchPlan {
                account: "g-deep".into(),
                provider: ProviderKind::Deep,
                chunks: view.chunks.clone(),
                start_budget_milli: total_budget_milli - scan_budget,
            },
        ]
    }

    fn continuation(&self) -> Continuation {
        Continuation::Sequential
    }

    fn revise(
        &mut self,
        finished_index: usize,
        observations: &Observations,
        plans: &mut [BranchPlan],
        _tariffs: &Tariffs,
    ) {
        if finished_index != 0 {
            return;
        }
        if let Some(deep) = plans.get_mut(1) {
            deep.chunks = rank_unresolved_by_score(deep, observations);
        }
    }

    fn observe_scan(&mut self, state: &ScanState) -> ScanDecision {
        // Scan exhaustion is the safe escalation point, as in arm E — not a
        // decision.
        if state.remaining == 0 {
            return ScanDecision::Escalate;
        }
        let context = scan_context(state);
        let state_key = scan_state_key(&context);
        let index = if self.policy.epsilon == 0.0 {
            self.policy.greedy(state_key)
        } else {
            self.policy.decide(state_key)
        };
        let decision = if index == 0 {
            ScanDecision::Continue
        } else {
            ScanDecision::Escalate
        };
        self.decisions.push((state_key, decision));
        decision
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct TdTrainingRecord {
    pub question_id: String,
    pub decision: usize,
    pub reward: f64,
    pub solved: bool,
}

/// Online training with an offline backward pass per episode: run with the
/// current policy, then update Q values from the terminal reward backward
/// through the decision chain.
pub fn train_td(
    policy: &mut TdPolicy,
    questions: &[Question],
    total_budget_milli: Amount,
    tariffs: &Tariffs,
) -> Vec<TdTrainingRecord> {
    let mut records = Vec::new();
    for (question_index, question) in questions.iter().enumerate() {
        // Per-question exploration variety: clones inherit the rng state.
        policy.tick_rng(question_index as u64 % 64 + 1);
        let mut strategy = TdSequentialStrategy::new(policy.clone());
        let report = run_arm(&mut strategy, question, total_budget_milli, tariffs);
        let decisions = strategy.take_decisions();
        let final_reward = reward_for(&report);
        for i in (0..decisions.len()).rev() {
            let (state, decision) = decisions[i];
            let action = match decision {
                ScanDecision::Continue => 0usize,
                ScanDecision::Escalate => 1usize,
            };
            let next = if i + 1 < decisions.len() {
                Some((
                    decisions[i + 1].0,
                    match decisions[i + 1].1 {
                        ScanDecision::Continue => 0usize,
                        ScanDecision::Escalate => 1usize,
                    },
                ))
            } else {
                None
            };
            policy.update_sarsa(state, action, next, final_reward);
            records.push(TdTrainingRecord {
                question_id: question.view.id.clone(),
                decision: action,
                reward: final_reward,
                solved: report.solved,
            });
        }
    }
    records
}
