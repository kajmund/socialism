//! Budget-manager policies: three simple baselines and the learning arm.
//!
//! Learner design (v1 lessons applied):
//!
//! - Tabular Q over the small discretized state (type, budget bracket,
//!   tiers) — v1 showed tabular beats parametric layers when the signal
//!   is weak, and this state is small enough to be fully tabular.
//! - Every-visit Monte Carlo credit per episode: the terminal reward is
//!   credited to every visited (state, action). Valid because the env is
//!   deterministic; this is v1's episodic credit (84-210 -> 325/500)
//!   without the myopic-shaping trap.
//! - Optimistic init drives exploration into unvisited actions (v1's
//!   feedback-starvation lesson) and epsilon anneals over the season.
//! - Minibatch: episodes are buffered and applied every `update_every`
//!   questions (spec 7); the frequency is configurable for the
//!   online-vs-minibatch comparison.
//! - Per-question RNG tick (v1's frozen-rng lesson).

use crate::env::{
    action_index, Action, Observation, Question, ACTION_COUNT, STRATEGY_COUNT, TIER_LEVELS,
};

/// Fixed decision rule or learner. Implementations must be deterministic
/// in eval mode and reproducible across runs (crate non-negotiable 4).
pub trait Policy {
    fn name(&self) -> &'static str;
    fn episode_start(&mut self, _question: &Question, _question_index: u64) {}
    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action;
    /// Per-step reward emitted by the env after each `step` (the learner
    /// needs the intermediate cost debits, not just the terminal total).
    fn on_step(&mut self, _step_reward_milli: i64) {}
    fn episode_end(&mut self, _reward_milli: i64) {}
    fn set_eval(&mut self, _eval: bool) {}
}

// ---------------------------------------------------------------------------
// Baselines

/// Per-episode memory for the baselines; reset when the question id changes.
#[derive(Default)]
struct EpisodeMem {
    question_id: String,
    last_invested: Option<usize>,
    prev_tier: u8,
    no_gain_streak: u8,
    no_gain_by_strategy: [u8; STRATEGY_COUNT],
    next_strategy: usize,
    est_marginal: [f64; STRATEGY_COUNT], // adaptive: tier-gain per milli, EMA
}

impl EpisodeMem {
    fn begin(&mut self, question: &Question) {
        self.question_id = question.id.clone();
        self.last_invested = None;
        self.prev_tier = 0;
        self.no_gain_streak = 0;
        self.no_gain_by_strategy = [0; STRATEGY_COUNT];
        self.next_strategy = 0;
        // Optimistic prior: 1 tier per 1000 milli until observed.
        self.est_marginal = [0.001; STRATEGY_COUNT];
    }

    /// Feed the tiers observed before deciding; returns the tier gain of
    /// the previous investment (0 if the previous action was not an invest).
    fn observe(&mut self, obs: &Observation) -> u8 {
        match self.last_invested {
            Some(s) => {
                let gain = obs.tiers[s].saturating_sub(self.prev_tier);
                self.prev_tier = obs.tiers[s];
                gain
            }
            None => 0,
        }
    }
}

fn investable(_obs: &Observation, valid: &[Action], s: usize) -> bool {
    valid
        .iter()
        .any(|a| matches!(a, Action::Invest(i, _) if *i == s))
}

/// Equal split: round-robin 5 coins across the three strategies until
/// three consecutive zero-gain investments.
pub struct EqualSplitPolicy {
    mem: EpisodeMem,
}

impl EqualSplitPolicy {
    pub fn new() -> Self {
        Self {
            mem: EpisodeMem::default(),
        }
    }
}

impl Policy for EqualSplitPolicy {
    fn name(&self) -> &'static str {
        "equal-split"
    }

    fn episode_start(&mut self, question: &Question, _question_index: u64) {
        self.mem.begin(question);
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if self.mem.question_id != obs.question_id {
            self.mem.begin(&Question {
                id: obs.question_id.clone(),
                qtype: obs.qtype,
                budget_milli: obs.remaining_milli,
            });
        }
        let gain = self.mem.observe(obs);
        if self.mem.last_invested.is_some() {
            if gain == 0 {
                self.mem.no_gain_streak += 1;
            } else {
                self.mem.no_gain_streak = 0;
            }
        }
        if self.mem.no_gain_streak >= 3 {
            return Action::Finish;
        }
        if !valid.contains(&Action::Invest(0, 5_000))
            && !valid.contains(&Action::Invest(1, 5_000))
            && !valid.contains(&Action::Invest(2, 5_000))
        {
            return Action::Finish;
        }
        for _ in 0..STRATEGY_COUNT {
            let s = self.mem.next_strategy;
            self.mem.next_strategy = (s + 1) % STRATEGY_COUNT;
            if investable(obs, valid, s) && valid.contains(&Action::Invest(s, 5_000)) {
                self.mem.last_invested = Some(s);
                self.mem.prev_tier = obs.tiers[s];
                return Action::Invest(s, 5_000);
            }
        }
        Action::Finish
    }
}

/// Sequential deterministic priority: all-in A until three consecutive
/// zero-gain investments, then B, then C, then finish.
pub struct SequentialPolicy {
    mem: EpisodeMem,
}

impl SequentialPolicy {
    pub fn new() -> Self {
        Self {
            mem: EpisodeMem::default(),
        }
    }
}

impl Policy for SequentialPolicy {
    fn name(&self) -> &'static str {
        "sequential"
    }

    fn episode_start(&mut self, question: &Question, _question_index: u64) {
        self.mem.begin(question);
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if self.mem.question_id != obs.question_id {
            self.mem.begin(&Question {
                id: obs.question_id.clone(),
                qtype: obs.qtype,
                budget_milli: obs.remaining_milli,
            });
        }
        let gain = self.mem.observe(obs);
        if self.mem.last_invested.is_some() {
            let s = self.mem.last_invested.unwrap();
            if gain == 0 {
                self.mem.no_gain_by_strategy[s] += 1;
                if self.mem.no_gain_by_strategy[s] >= 3 {
                    self.mem.next_strategy = s + 1;
                    self.mem.no_gain_by_strategy[s] = 0;
                }
            } else {
                self.mem.no_gain_by_strategy[s] = 0;
            }
        }
        while self.mem.next_strategy < STRATEGY_COUNT {
            let s = self.mem.next_strategy;
            if valid.contains(&Action::Invest(s, 5_000)) {
                self.mem.last_invested = Some(s);
                self.mem.prev_tier = obs.tiers[s];
                return Action::Invest(s, 5_000);
            }
            self.mem.next_strategy += 1;
        }
        Action::Finish
    }
}

/// Heuristic adaptive: greedy on the observed marginal tier-gain per coin
/// (EMA per strategy, optimistic prior), 5 coins per investment.
pub struct AdaptiveGreedyPolicy {
    mem: EpisodeMem,
}

impl AdaptiveGreedyPolicy {
    pub fn new() -> Self {
        Self {
            mem: EpisodeMem::default(),
        }
    }
}

impl Policy for AdaptiveGreedyPolicy {
    fn name(&self) -> &'static str {
        "adaptive-greedy"
    }

    fn episode_start(&mut self, question: &Question, _question_index: u64) {
        self.mem.begin(question);
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if self.mem.question_id != obs.question_id {
            self.mem.begin(&Question {
                id: obs.question_id.clone(),
                qtype: obs.qtype,
                budget_milli: obs.remaining_milli,
            });
        }
        if let Some(s) = self.mem.last_invested {
            let gain = obs.tiers[s].saturating_sub(self.mem.prev_tier);
            if gain == 0 {
                self.mem.no_gain_streak += 1;
            } else {
                self.mem.no_gain_streak = 0;
            }
            let sample = gain as f64 / 5_000.0;
            let est = self.mem.est_marginal[s];
            self.mem.est_marginal[s] = 0.5 * est + 0.5 * sample;
        }
        // Plateau stop: the EMA never reaches exactly zero, so without
        // this the rule invests until budget exhaustion (measured: mean
        // 0 on the capability world's held-out set). Three consecutive
        // zero-gain investments = the strategy mix is saturated.
        if self.mem.no_gain_streak >= 3 {
            return Action::Finish;
        }
        let mut best: Option<(usize, f64)> = None;
        for s in 0..STRATEGY_COUNT {
            if !investable(obs, valid, s) {
                continue;
            }
            let est = self.mem.est_marginal[s];
            let better = match best {
                Some((_, be)) => est > be,
                None => true,
            };
            if better {
                best = Some((s, est));
            }
        }
        match best {
            Some((s, est)) if est > 0.0 && valid.contains(&Action::Invest(s, 5_000)) => {
                self.mem.last_invested = Some(s);
                self.mem.prev_tier = obs.tiers[s];
                Action::Invest(s, 5_000)
            }
            _ => Action::Finish,
        }
    }
}

// ---------------------------------------------------------------------------
// Learning arm: tabular Q-learning with a backward pass over the
// recorded decision chain per episode — v1's td.rs pattern, applied to
// budget decisions. The episode's terminal reward propagates backward
// with discount gamma in a single pass, so the credit signal reaches the
// front of a 10-30 step chain without the variance of every-visit MC.
// (Measured: every-visit MC over random exploration tails left the
// learner at ~47k vs a 95k baseline, and backward Sarsa with optimistic
// init inflated predecessors — backward Q-learning with zero-init is the
// fix.)
//
// State = (qtype, tiers) — the budget bracket is deliberately NOT part of
// the key. The remaining budget only matters through action masking
// (amounts above remaining are invalid), and including the bracket made
// the table 4x sparser than the sample budget could support (measured:
// the learner lost money with 38k cells and ~6k samples). This is the
// v1 capacity lesson applied: keep the table small enough that every
// reached cell gets enough samples.

/// State key: (qtype, tierA, tierB, tierC).
fn state_index(qtype: u8, tiers: &[u8; STRATEGY_COUNT]) -> usize {
    qtype as usize * (TIER_LEVELS as usize).pow(3)
        + tiers[0] as usize * (TIER_LEVELS as usize).pow(2)
        + tiers[1] as usize * TIER_LEVELS as usize
        + tiers[2] as usize
}

/// Flat Q index: (qtype, tierA, tierB, tierC, action).
fn q_index(qtype: u8, tiers: &[u8; STRATEGY_COUNT], action: usize) -> usize {
    state_index(qtype, tiers) * ACTION_COUNT + action
}

const Q_TABLE_STATES: usize = 4 * (TIER_LEVELS as usize).pow(3);
const Q_TABLE_LEN: usize = Q_TABLE_STATES * ACTION_COUNT;

/// Q-init: zero. Coverage comes from the UCB exploration bonus, not
/// optimism — an optimistic init propagates backward through the
/// bootstrap targets and inflates every predecessor (measured).
const Q_INIT: f64 = 0.0;

/// UCB exploration constant: drives the learner into undersampled
/// actions (and thereby into deep, never-reached states) — v1's fix for
/// feedback starvation, where greedy stops at the first state and the
/// deep chains never get any samples.
const UCB_C: f64 = 20_000.0;

pub struct McQLearner {
    q: Vec<f64>,
    counts: Vec<f64>,
    alpha: f64,
    gamma: f64,
    epsilon_start: f64,
    epsilon_min: f64,
    epsilon_decay: f64,
    update_every: usize,
    rng_state: u64,
    eval: bool,
    episodes_seen: u64,
    /// (state, action, valid action indices) of the current episode, in
    /// order; the valid set is what the backward max bootstraps over.
    episode: Vec<(usize, usize, Vec<u8>, i64)>,
    /// Buffered episodes (spec 7 minibatch).
    pending: Vec<Vec<(usize, usize, Vec<u8>, i64)>>,
    /// How often a state-action was updated — kept for reporting.
    pub updates: u64,
}

impl McQLearner {
    pub fn new(seed: u64) -> Self {
        Self {
            q: vec![Q_INIT; Q_TABLE_LEN],
            counts: vec![0.0; Q_TABLE_LEN],
            alpha: 1.0,
            gamma: 1.0,
            epsilon_start: 0.1,
            epsilon_min: 0.02,
            epsilon_decay: 0.99,
            update_every: 20,
            rng_state: seed.max(1),
            eval: false,
            episodes_seen: 0,
            episode: Vec::new(),
            pending: Vec::new(),
            updates: 0,
        }
    }

    /// Configurable update frequency (spec 7: online vs minibatch).
    pub fn with_update_every(mut self, every: usize) -> Self {
        self.update_every = every.max(1);
        self
    }

    /// Diagnostic: current Q estimate for one (state, action).
    pub fn q_at(&self, qtype: u8, tiers: &[u8; STRATEGY_COUNT], action: usize) -> f64 {
        self.q[q_index(qtype, tiers, action)]
    }

    fn next_f64(&mut self) -> f64 {
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        (x >> 11) as f64 / (1u64 << 53) as f64
    }

    /// v1's frozen-rng lesson: decorrelate per question.
    pub fn tick_rng(&mut self, steps: u64) {
        for _ in 0..steps {
            self.next_f64();
        }
    }

    fn epsilon(&self) -> f64 {
        let decayed = self.epsilon_start * self.epsilon_decay.powi(self.episodes_seen as i32);
        decayed.max(self.epsilon_min)
    }

    fn q_value(&self, qtype: u8, tiers: &[u8; STRATEGY_COUNT], action: usize) -> f64 {
        self.q[q_index(qtype, tiers, action)]
    }

    /// Best valid action by Q; deterministic tie-break to the lowest index.
    fn greedy(&self, obs: &Observation, valid: &[Action]) -> Action {
        let mut best: Option<(Action, f64)> = None;
        for &a in valid {
            let v = self.q_value(obs.qtype, &obs.tiers, action_index(a));
            let better = match best {
                Some((_, bv)) => {
                    v > bv || (v == bv && action_index(a) < action_index(best.unwrap().0))
                }
                None => true,
            };
            if better {
                best = Some((a, v));
            }
        }
        best.expect("valid is never empty (Finish is always valid)")
            .0
    }

    /// Apply buffered episodes: backward Q-learning over each recorded
    /// decision chain with per-step rewards (cost debits make the tier
    /// state Markov, so the bootstrap targets are consistent). The last
    /// step's target is its own step reward; each earlier step targets
    /// `r + gamma * max Q(successor)`, so credit reaches the whole chain
    /// in a single pass (v1's td.rs pattern, off-policy max variant).
    fn flush(&mut self) {
        for episode in std::mem::take(&mut self.pending) {
            let mut successor_max = 0.0f64; // terminal state value
            for (state, action, valid, r) in episode.iter().rev() {
                let target = *r as f64 + self.gamma * successor_max;
                let q = &mut self.q[state * ACTION_COUNT + action];
                *q += self.alpha * (target - *q);
                self.updates += 1;
                // For the previous step, the successor is THIS state;
                // its value is the max over the actions valid here.
                let mut max_here = f64::NEG_INFINITY;
                for &a in valid {
                    let v = self.q[state * ACTION_COUNT + a as usize];
                    if v > max_here {
                        max_here = v;
                    }
                }
                successor_max = max_here;
            }
        }
    }
}

impl Policy for McQLearner {
    fn name(&self) -> &'static str {
        "mc-q-learner"
    }

    fn episode_start(&mut self, _question: &Question, question_index: u64) {
        // Decorrelate exploration per question (v1's frozen-rng lesson).
        self.tick_rng(question_index % 64 + 1);
        self.episode.clear();
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        let state = state_index(obs.qtype, &obs.tiers);
        let action = if self.eval {
            self.greedy(obs, valid)
        } else {
            // UCB exploration: value plus an exploration bonus that
            // decays with visits, so undersampled actions (and the deep
            // states behind them) get tried even when greedy would stop.
            let mut best: Option<(Action, f64)> = None;
            for &a in valid {
                let idx = action_index(a);
                let n_sa = self.counts[state * ACTION_COUNT + idx];
                let n_s: f64 = (0..ACTION_COUNT)
                    .map(|i| self.counts[state * ACTION_COUNT + i])
                    .sum();
                let bonus = if n_sa < 1.0 {
                    UCB_C * 3.0
                } else {
                    UCB_C * ((n_s + 1.0).ln() / n_sa).sqrt()
                };
                let v = self.q[state * ACTION_COUNT + idx] + bonus;
                let better = match best {
                    Some((_, bv)) => v > bv || (v == bv && idx < action_index(best.unwrap().0)),
                    None => true,
                };
                if better {
                    best = Some((a, v));
                }
            }
            let greedy_ucb = best.expect("valid is never empty").0;
            if self.next_f64() < self.epsilon() {
                let pick = (self.next_f64() * valid.len() as f64) as usize;
                valid[pick.min(valid.len() - 1)]
            } else {
                greedy_ucb
            }
        };
        if !self.eval {
            self.counts[state * ACTION_COUNT + action_index(action)] += 1.0;
        }
        let valid_indices: Vec<u8> = valid.iter().map(|&a| action_index(a) as u8).collect();
        self.episode
            .push((state, action_index(action), valid_indices, 0));
        action
    }

    fn on_step(&mut self, step_reward_milli: i64) {
        // Patch the step reward into the entry recorded by `act`.
        if let Some(last) = self.episode.last_mut() {
            last.3 = step_reward_milli;
        }
    }

    fn episode_end(&mut self, _reward_milli: i64) {
        self.episodes_seen += 1;
        if !self.eval {
            self.pending.push(std::mem::take(&mut self.episode));
            if self.pending.len() >= self.update_every {
                self.flush();
            }
        } else {
            self.episode.clear();
        }
    }

    fn set_eval(&mut self, eval: bool) {
        self.eval = eval;
    }
}
