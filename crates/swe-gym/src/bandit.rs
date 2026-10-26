//! First learned policy: a contextual linear bandit (SGD) over a single
//! budget decision — how many deep calls to authorize after the scan pass.
//!
//! Facit-free: contexts use provider scores, findings and budgets only. All
//! training data is synthetic and scripted (see gen.rs); every evaluation
//! reports that. The frozen bench is the held-out test set.

use std::collections::HashMap;

use crate::benchmark::{run_arm, ArmReport};
use crate::ledger::Amount;
use crate::strategy::{
    rank_unresolved_by_score, BranchPlan, Continuation, Observations, ProviderKind, Question,
    QuestionView, ScanDecision, ScanState, Strategy, Tariffs,
};

/// Context dimension: bias, gap, top1..top3 scores, affordable deep calls.
pub const DIM: usize = 6;
/// Actions: authorize 0..=3 deep calls on the top-ranked unresolved chunks.
pub const K: usize = 4;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Deep0,
    Deep1,
    Deep2,
    Deep3,
}

impl Action {
    pub fn from_k(k: usize) -> Self {
        match k {
            0 => Self::Deep0,
            1 => Self::Deep1,
            2 => Self::Deep2,
            _ => Self::Deep3,
        }
    }
    pub fn as_usize(self) -> usize {
        match self {
            Self::Deep0 => 0,
            Self::Deep1 => 1,
            Self::Deep2 => 2,
            Self::Deep3 => 3,
        }
    }

    pub fn deep_calls(self) -> usize {
        self.as_usize()
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Context {
    pub features: [f64; DIM],
}

/// First index with the maximum score; ties prefer the smallest action, so a
/// converged policy authorizes no more deep calls than it must.
fn argmax_first(scores: &[f64; K]) -> Action {
    let mut best = 0;
    for k in 1..K {
        if scores[k] > scores[best] {
            best = k;
        }
    }
    Action::from_k(best)
}

impl Context {
    /// The coverage gap at decision time, in whole chunks.
    pub fn gap(&self) -> usize {
        self.features[1].round() as usize
    }
}

/// Linear bandit with SGD updates, epsilon-greedy exploration plus a UCB
/// bonus per action count. One weight vector per action; deterministic per
/// seed.
///
/// The UCB term matters: with pure epsilon-greedy, actions that lose the
/// early argmax are starved of feedback and never get a chance to prove their
/// value (observed empirically: Deep2 stayed near its init and the policy
/// gave up instead of escalating). The bonus forces sampling until counts
/// balance, then decays.
#[derive(Clone, Debug)]
pub struct BanditPolicy {
    weights: [[f64; DIM]; K],
    counts: [u64; K],
    epsilon: f64,
    learning_rate: f64,
    rng_state: u64,
    updates: u64,
}

impl BanditPolicy {
    pub fn new(seed: u64, epsilon: f64, learning_rate: f64) -> Self {
        let mut policy = Self {
            weights: [[0.0; DIM]; K],
            counts: [0; K],
            epsilon,
            learning_rate,
            rng_state: seed.max(1),
            updates: 0,
        };
        let mut draws = Vec::with_capacity(DIM * K);
        for _ in 0..DIM * K {
            draws.push(policy.next_f64());
        }
        let mut index = 0;
        for action in policy.weights.iter_mut() {
            for (d, weight) in action.iter_mut().enumerate() {
                if d == 0 {
                    // Optimistic bias: every action looks valuable until
                    // sampled enough to prove otherwise. Without it, the
                    // first action to pull ahead starves the rest of feedback.
                    *weight = 10.0;
                } else {
                    *weight = (draws[index] - 0.5) * 0.2; // small symmetric init
                }
                index += 1;
            }
        }
        policy
    }

    fn next_f64(&mut self) -> f64 {
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        (x >> 11) as f64 / (1u64 << 53) as f64
    }

    pub fn value(&self, action: Action, context: &Context) -> f64 {
        self.weights[action.as_usize()]
            .iter()
            .zip(&context.features)
            .map(|(weight, feature)| weight * feature)
            .sum()
    }

    /// Epsilon-greedy with a UCB bonus over the action counts.
    pub fn decide(&mut self, context: &Context) -> Action {
        if self.next_f64() < self.epsilon {
            let k = (self.next_f64() * K as f64) as usize;
            return Action::from_k(k.min(K - 1));
        }
        self.ucb(context)
    }

    fn ucb(&self, context: &Context) -> Action {
        let total = self.counts.iter().sum::<u64>() as f64 + 1.0;
        let mut scores = [0.0; K];
        for k in 0..K {
            let action = Action::from_k(k);
            scores[k] = self.value(action, context)
                + 2.0 * (total.ln() / (1.0 + self.counts[k] as f64)).sqrt();
        }
        argmax_first(&scores)
    }

    /// Greedy arm, fully deterministic (used for the frozen evaluation).
    pub fn greedy(&self, context: &Context) -> Action {
        let mut scores = [0.0; K];
        for k in 0..K {
            scores[k] = self.value(Action::from_k(k), context);
        }
        argmax_first(&scores)
    }

    pub fn update(&mut self, context: &Context, action: Action, reward: f64) {
        let prediction = self.value(action, context);
        let error = reward - prediction;
        let k = action.as_usize();
        for d in 0..DIM {
            self.weights[k][d] = (self.weights[k][d]
                + self.learning_rate * error * context.features[d])
                .clamp(-50.0, 50.0);
        }
        self.counts[k] += 1;
        self.updates += 1;
    }

    pub fn updates(&self) -> u64 {
        self.updates
    }

    /// Freeze exploration for evaluation.
    pub fn set_epsilon(&mut self, epsilon: f64) {
        self.epsilon = epsilon;
    }
}

/// Strategy wrapper: scan first (same plan as A/C), then the policy decides
/// how many top-ranked unresolved chunks to deep-analyze. Exactly one trained
/// decision per run — the single budget decision of the first experiment.
pub struct BanditStrategy {
    policy: BanditPolicy,
    last: Option<(Context, Action)>,
}

impl BanditStrategy {
    pub fn new(policy: BanditPolicy) -> Self {
        Self { policy, last: None }
    }

    /// The (context, action) of this run's decision, for the trainer.
    pub fn take_last(&mut self) -> Option<(Context, Action)> {
        self.last.take()
    }
}

impl Strategy for BanditStrategy {
    fn name(&self) -> &'static str {
        "D bandit (linjär SGD)"
    }

    fn plan(
        &self,
        view: &QuestionView,
        total_budget_milli: Amount,
        tariffs: &Tariffs,
    ) -> Vec<BranchPlan> {
        let scan_cost = tariffs
            .scan_milli
            .saturating_mul(view.chunks.len() as Amount);
        let scan_budget = scan_cost.min(total_budget_milli);
        vec![
            BranchPlan {
                account: "d-scan".into(),
                provider: ProviderKind::Scan,
                chunks: view.chunks.clone(),
                start_budget_milli: scan_budget,
            },
            BranchPlan {
                account: "d-deep".into(),
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
        tariffs: &Tariffs,
    ) {
        if finished_index != 0 {
            return;
        }
        let Some(deep) = plans.get_mut(1) else {
            return;
        };
        let ranked = rank_unresolved_by_score(deep, observations);
        let context = build_context(observations, &ranked, deep.start_budget_milli, tariffs);
        let action = self.policy.decide(&context);
        deep.chunks = ranked.into_iter().take(action.deep_calls()).collect();
        self.last = Some((context, action));
    }
}

/// Facit-free context at the escalation point: gap, the three best unresolved
/// scores and how many deep calls the branch budget affords.
pub fn build_context(
    observations: &Observations,
    ranked: &[String],
    deep_budget_milli: Amount,
    tariffs: &Tariffs,
) -> Context {
    let gap = observations
        .required
        .saturating_sub(observations.found.len())
        .min(3) as f64;
    let scores: HashMap<String, u32> = observations.scan_scores.iter().cloned().collect();
    let top = |index: usize| -> f64 {
        ranked
            .get(index)
            .and_then(|chunk| scores.get(chunk))
            .copied()
            .unwrap_or(0) as f64
            / 10_000.0
    };
    let affordable = (deep_budget_milli / tariffs.deep_milli).min(3) as f64;
    Context {
        features: [1.0, gap, top(0), top(1), top(2), affordable],
    }
}

/// Reward for a run with a bandit decision: verified answers pay 10 minus the
/// deep calls spent; failures cost exactly the deep calls burned. A give-up
/// (k = 0, not solved) therefore scores 0.
pub fn reward_for(report: &ArmReport) -> f64 {
    let deep_made = report
        .calls
        .iter()
        .filter(|call| call.provider == "deep")
        .count() as f64;
    if report.solved {
        10.0 - deep_made
    } else {
        -deep_made
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct TrainingRecord {
    pub question_id: String,
    pub gap: usize,
    pub action: usize,
    pub reward: f64,
    pub solved: bool,
}

/// Online training: one real (synthetic) run per question, one policy update
/// per decision. Questions where the scan pass already solved the task
/// produce no decision and no update.
pub fn train_bandit(
    policy: &mut BanditPolicy,
    questions: &[Question],
    total_budget_milli: Amount,
    tariffs: &Tariffs,
) -> Vec<TrainingRecord> {
    let mut records = Vec::with_capacity(questions.len());
    for question in questions {
        let mut strategy = BanditStrategy::new(policy.clone());
        let report = run_arm(&mut strategy, question, total_budget_milli, tariffs);
        if let Some((context, action)) = strategy.take_last() {
            let reward = reward_for(&report);
            policy.update(&context, action, reward);
            records.push(TrainingRecord {
                question_id: question.view.id.clone(),
                gap: context.gap(),
                action: action.as_usize(),
                reward,
                solved: report.solved,
            });
        }
    }
    records
}

// ---------------------------------------------------------------------------
// The second decision point: continue scanning or escalate, per scan step.
// Sequential RL (multiple dependent decisions per run), reward-shaped.
// ---------------------------------------------------------------------------

/// Discretize the checkpoint context: gap (2 bits), best-score band (2
/// bits), last-score band (2 bits), remaining band (2 bits). Shared by the
/// tabular bandit and the TD policy.
///
/// The remaining feature got a second bit for the structured-corpus
/// experiment: scan position is real, facit-free information when evidence
/// is regionally clustered, and finer bands let the policy learn the region
/// boundary.
pub fn scan_state_key(context: &Context) -> u64 {
    let band = |score: f64| -> u64 {
        let bp = (score * 10_000.0).round() as u64;
        if bp >= 5_000 {
            3
        } else if bp >= 3_000 {
            2
        } else if bp >= 1_000 {
            1
        } else {
            0
        }
    };
    let gap = (context.features[1].round() as u64).min(3);
    let best = band(context.features[5]);
    let last = band(context.features[4]);
    let remaining_count = (context.features[2] * 10.0).round() as u64;
    let remaining = if remaining_count >= 8 {
        0
    } else if remaining_count >= 5 {
        1
    } else if remaining_count >= 2 {
        2
    } else {
        3
    };
    gap | (best << 2) | (last << 4) | (remaining << 6)
}

pub const SCAN_ACTIONS: usize = 2;
/// Escalate may override scanning only after this many samples in a state.
pub const MIN_SAMPLES: f64 = 5.0;

/// Second bandit: the per-scan-step continue/escalate decision. A tabular
/// contextual bandit over a discretized checkpoint state — running mean per
/// (state, action) with a UCB bonus and optimistic cold start.
///
/// The first attempt used a linear SGD model; on the noisy corpus it
/// overfitted collinear features and extrapolated wild values (continue
/// learned -6 against an empirical mean of +1.5). A mean table cannot
/// extrapolate — it learns exactly what the data says, per state.
#[derive(Clone, Debug)]
pub struct ScanPolicy {
    /// state key → per action [reward_sum, count].
    table: HashMap<u64, [[f64; 2]; SCAN_ACTIONS]>,
    epsilon: f64,
    rng_state: u64,
    updates: u64,
}

impl ScanPolicy {
    pub fn new(seed: u64, epsilon: f64) -> Self {
        Self {
            table: HashMap::new(),
            epsilon,
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

    fn state_key(context: &Context) -> u64 {
        scan_state_key(context)
    }

    fn mean(&self, key: u64, action: usize) -> f64 {
        match self.table.get(&key) {
            Some(entry) if entry[action][1] > 0.0 => entry[action][0] / entry[action][1],
            _ => 2.0, // optimistic cold start: untried actions look promising
        }
    }

    fn count(&self, key: u64, action: usize) -> f64 {
        self.table
            .get(&key)
            .map(|entry| entry[action][1])
            .unwrap_or(0.0)
    }

    /// Epsilon-greedy with a UCB bonus over the action counts in this state.
    pub fn decide_index(&mut self, context: &Context) -> usize {
        if self.next_f64() < self.epsilon {
            return (self.next_f64() * SCAN_ACTIONS as f64) as usize;
        }
        let key = Self::state_key(context);
        let total = self.count(key, 0) + self.count(key, 1) + 1.0;
        let mut best = 0;
        for k in 1..SCAN_ACTIONS {
            let score = |action: usize| {
                self.mean(key, action) + 2.0 * (total.ln() / (1.0 + self.count(key, action))).sqrt()
            };
            if score(k) > score(best) {
                best = k;
            }
        }
        best
    }

    /// Greedy, deterministic — used when frozen (epsilon = 0). Ties continue,
    /// and escalate needs at least `MIN_SAMPLES` observations in this state
    /// before it may override scanning: one lucky sample must not lock in an
    /// early stop (observed live — single +8 samples froze escalation in
    /// states where it was noise).
    pub fn greedy_index(&self, context: &Context) -> usize {
        let key = Self::state_key(context);
        if self.count(key, 1) < MIN_SAMPLES {
            return 0;
        }
        let mut best = 0;
        for k in 1..SCAN_ACTIONS {
            if self.mean(key, k) > self.mean(key, best) {
                best = k;
            }
        }
        best
    }

    pub fn update_index(&mut self, context: &Context, action: usize, reward: f64) {
        let key = Self::state_key(context);
        let entry = self.table.entry(key).or_insert([[0.0; 2]; SCAN_ACTIONS]);
        entry[action][0] += reward;
        entry[action][1] += 1.0;
        self.updates += 1;
    }

    pub fn set_epsilon(&mut self, epsilon: f64) {
        self.epsilon = epsilon;
    }

    /// Advance the rng. Cloned strategies inherit the master's rng state, so
    /// without this every question would explore identically — observed live:
    /// the first decision froze on escalate and never recovered.
    pub fn tick_rng(&mut self, steps: u64) {
        for _ in 0..steps {
            self.next_f64();
        }
    }

    pub fn updates(&self) -> u64 {
        self.updates
    }
}

/// Facit-free context at a scan checkpoint: gap, remaining scans, found
/// density and the last/best scores seen so far.
pub fn scan_context(state: &ScanState) -> Context {
    let gap = state.required.saturating_sub(state.found).min(3) as f64;
    let density = state.found as f64 / state.scanned.max(1) as f64;
    Context {
        features: [
            1.0,
            gap,
            state.remaining.min(10) as f64 / 10.0,
            density,
            state.last_score_bp as f64 / 10_000.0,
            state.best_score_bp as f64 / 10_000.0,
        ],
    }
}

/// Arm E: the sequential bandit. Same plan as C, but after each scan call the
/// policy decides between continuing and escalating. Frozen = greedy
/// (epsilon 0).
pub struct SequentialBanditStrategy {
    policy: ScanPolicy,
    decisions: Vec<(Context, ScanDecision)>,
}

impl SequentialBanditStrategy {
    pub fn new(policy: ScanPolicy) -> Self {
        Self {
            policy,
            decisions: Vec::new(),
        }
    }

    pub fn take_decisions(&mut self) -> Vec<(Context, ScanDecision)> {
        std::mem::take(&mut self.decisions)
    }
}

impl Strategy for SequentialBanditStrategy {
    fn name(&self) -> &'static str {
        "E sekventiell bandit"
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
                account: "e-scan".into(),
                provider: ProviderKind::Scan,
                chunks,
                start_budget_milli: scan_budget,
            },
            BranchPlan {
                account: "e-deep".into(),
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
        // Same ranking as arm C: escalate toward the most suspicious
        // unresolved chunks first. Without this the deep phase is arm A's
        // blind document-order escalation.
        if finished_index != 0 {
            return;
        }
        if let Some(deep) = plans.get_mut(1) {
            deep.chunks = rank_unresolved_by_score(deep, observations);
        }
    }

    fn observe_scan(&mut self, state: &ScanState) -> ScanDecision {
        // Scan exhaustion is C's safe escalation point, not a decision: with
        // no chunks left, escalating is the only move that can still solve.
        if state.remaining == 0 {
            return ScanDecision::Escalate;
        }
        let context = scan_context(state);
        let index = if self.policy.epsilon == 0.0 {
            self.policy.greedy_index(&context)
        } else {
            self.policy.decide_index(&context)
        };
        let decision = if index == 0 {
            ScanDecision::Continue
        } else {
            ScanDecision::Escalate
        };
        self.decisions.push((context, decision));
        decision
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SeqTrainingRecord {
    pub question_id: String,
    pub decision: usize,
    pub reward: f64,
    pub solved: bool,
}

/// Online training for the sequential decision. Reward shaping, v0:
/// - Continue pays +9 when the next scan finds evidence, -1 when it does not
///   (a scan coin well spent vs wasted — the shaped local reward).
/// - Escalate, and the final continue at scan exhaustion, receive the run's
///   final reward (verified answers pay 10 minus deep calls; failures cost
///   the deep calls burned).
/// The shaping is explicit and documented; the policy is still facit-free.
pub fn train_sequential(
    policy: &mut ScanPolicy,
    questions: &[Question],
    total_budget_milli: Amount,
    tariffs: &Tariffs,
) -> Vec<SeqTrainingRecord> {
    let mut records = Vec::new();
    for (question_index, question) in questions.iter().enumerate() {
        // Per-question exploration variety: the clone below inherits the
        // master's rng state, so advance it first.
        policy.tick_rng(question_index as u64 % 64 + 1);
        let mut strategy = SequentialBanditStrategy::new(policy.clone());
        let report = run_arm(&mut strategy, question, total_budget_milli, tariffs);
        let decisions = strategy.take_decisions();
        let final_reward = reward_for(&report);
        let _scan_calls = report
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
        for (_i, (context, decision)) in decisions.iter().enumerate() {
            // Episodic credit: every decision receives the run's final
            // reward. Both arms then estimate the same quantity — the run
            // outcome from that checkpoint — and the comparison
            // continue-vs-escalate is well-defined. The earlier local +9/-1
            // shaping optimized a different objective and lost to arm C.
            let action = match decision {
                ScanDecision::Escalate => 1usize,
                ScanDecision::Continue => 0usize,
            };
            policy.update_index(context, action, final_reward);
            records.push(SeqTrainingRecord {
                question_id: question.view.id.clone(),
                decision: action,
                reward: final_reward,
                solved: report.solved,
            });
        }
    }
    records
}
