//! RealEnv: the v2 gym over the frozen real legal bench (step 6 of
//! docs/SWE_Sweycoins_v2.md).
//!
//! Strategies (same Action interface as the synthetic env):
//!
//! - **A** = JEV scan in similarity order (the arm-H engine — v1's best
//!   measured real policy), 1 coin per chunk (tariff `scan`).
//! - **B** = JEV scan in document order (the arm-A engine), 1 coin per chunk.
//! - **C** = deep/LLM analysis — **masked**: the frozen fixtures contain no
//!   deep answers, so the real env cannot model it honestly. A documented
//!   limitation, loud not silent: investing in C is an invalid action.
//!
//! State/observation: same shape as the synthetic env. Progress tiers are
//! the facit-free signal v1's scanner already observed: findings per
//! strategy (`tier_s = min(4, hits_found_by_s)`). Quality — the facit —
//! is evaluated only at episode end: `hits / required`, capped at 1.0.
//!
//! Question type: a pre-registered observable rule — bucket by chunk
//! count (the only facit-free scalar in the bench besides the question
//! text). This is a proxy, not a learned feature; the transfer test's
//! whole point is to find out whether it suffices. It is recorded here
//! so the rule cannot be tuned after seeing results.
//!
//! All money flows through the ledger with per-step accounting: each
//! INVEST reserves the granted amount, settles the ACTUAL scan cost and
//! releases the unspent remainder — the real settle path, unlike the
//! synthetic env's fixed-cost segments.

use std::collections::HashSet;

use crate::env::{
    budget_bracket, Action, Observation, Status, StepInfo, INVEST_AMOUNTS_MILLI, MIN_INVEST_MILLI,
    STRATEGY_COUNT, TIER_MAX,
};
use crate::ledger::{Amount, Ledger};
use crate::provider::{ReplayProvider, ResearchProvider};

/// Pre-registered observable type rule (see module docs). Chunk count
/// buckets: <=400 -> 0, <=700 -> 1, <=900 -> 2, else 3.
pub fn observable_qtype(chunk_count: usize) -> u8 {
    match chunk_count {
        c if c <= 400 => 0,
        c if c <= 700 => 1,
        c if c <= 900 => 2,
        _ => 3,
    }
}

/// One real question for the budget manager: the facit-free view plus
/// the facit (evaluator only, same split as bench.rs).
pub struct RealQuestion {
    pub id: String,
    pub qtype: u8,
    pub chunks: Vec<String>,     // document order
    pub scan_order: Vec<String>, // similarity order; empty = document order
    pub required: usize,
    pub evidence: HashSet<String>,
    pub budget_milli: Amount,
    pub fixture_source: String,
}

pub struct RealEnv {
    replay: Option<ReplayProvider>,
    base_reward_milli: Amount,
    max_steps: u32,
    question: Option<RealQuestion>,
    ledger: Ledger,
    key_seq: u64,
    cursors: [usize; 2],
    hits_by: [u8; 2],
    found: HashSet<String>,
    remaining_milli: Amount,
    spent_milli: [Amount; STRATEGY_COUNT],
    steps: u32,
    done: bool,
    obs: Option<Observation>,
}

impl RealEnv {
    pub fn new(base_reward_milli: Amount) -> Self {
        Self {
            replay: None,
            base_reward_milli,
            max_steps: 32,
            question: None,
            ledger: Ledger::new(),
            key_seq: 0,
            cursors: [0, 0],
            hits_by: [0, 0],
            found: HashSet::new(),
            remaining_milli: 0,
            spent_milli: [0; STRATEGY_COUNT],
            steps: 0,
            done: false,
            obs: None,
        }
    }

    fn next_key(&mut self, label: &str) -> String {
        self.key_seq += 1;
        format!("{label}:{}", self.key_seq)
    }

    fn tiers(&self) -> [u8; STRATEGY_COUNT] {
        [
            self.hits_by[0].min(TIER_MAX),
            self.hits_by[1].min(TIER_MAX),
            0,
        ]
    }

    fn quality(&self) -> f64 {
        let q = self.question.as_ref().expect("reset before quality");
        if q.required == 0 {
            return 1.0;
        }
        (self.found.len() as f64 / q.required as f64).min(1.0)
    }

    fn finish(&mut self, reason: &str) -> Result<(Observation, StepInfo), String> {
        let obs = self.obs.clone().expect("reset before finish");
        let reward = (self.quality() * self.base_reward_milli as f64).round() as i64;
        if reward > 0 {
            let run_id = obs.question_id.clone();
            let key = self.next_key("reward");
            self.ledger
                .reward(&run_id, "training", reward as Amount, &key)
                .map_err(|e| e.to_string())?;
        }
        self.done = true;
        Ok((
            obs,
            StepInfo {
                reward_milli: reward,
                gained_tiers: [0; STRATEGY_COUNT],
                cost_milli: 0,
                done: true,
                reason: reason.to_string(),
                ledger_events_added: 0,
            },
        ))
    }

    pub fn ledger(&self) -> &Ledger {
        &self.ledger
    }

    /// Verified findings so far (facit-evaluated; exposed for reporting
    /// and accounting tests only).
    pub fn found_count(&self) -> usize {
        self.found.len()
    }

    pub fn observation(&self) -> &Observation {
        self.obs.as_ref().expect("reset before observe")
    }

    pub fn reset(&mut self, q: &RealQuestion) -> Result<Observation, String> {
        self.replay = Some(ReplayProvider::load(&q.fixture_source)?);
        self.question = Some(RealQuestion {
            id: q.id.clone(),
            qtype: q.qtype,
            chunks: q.chunks.clone(),
            scan_order: q.scan_order.clone(),
            required: q.required,
            evidence: q.evidence.clone(),
            budget_milli: q.budget_milli,
            fixture_source: String::new(),
        });
        self.max_steps = (q.chunks.len() as u32) + 16;
        self.ledger = Ledger::new();
        self.key_seq = 0;
        let alloc_key = self.next_key("alloc");
        self.ledger
            .allocate(&q.id, "exec", q.budget_milli, &alloc_key)
            .map_err(|e| e.to_string())?;
        self.cursors = [0, 0];
        self.hits_by = [0, 0];
        self.found = HashSet::new();
        self.remaining_milli = q.budget_milli;
        self.spent_milli = [0; STRATEGY_COUNT];
        self.steps = 0;
        self.done = false;
        let obs = Observation {
            question_id: q.id.clone(),
            qtype: q.qtype,
            remaining_milli: q.budget_milli,
            bracket: budget_bracket(q.budget_milli),
            tiers: [0; STRATEGY_COUNT],
            found: 0,
            statuses: [Status::Idle; STRATEGY_COUNT],
            spent_milli: [0; STRATEGY_COUNT],
            steps: 0,
        };
        self.obs = Some(obs.clone());
        Ok(obs)
    }

    pub fn valid_actions(&self) -> Vec<Action> {
        let obs = match &self.obs {
            Some(o) if !self.done => o,
            _ => return vec![],
        };
        let mut valid = Vec::new();
        // Strategy C (deep) is deliberately absent: no frozen deep data.
        for s in [0usize, 1] {
            match obs.statuses[s] {
                Status::Paused | Status::Stopped => {}
                _ => {
                    for amount in INVEST_AMOUNTS_MILLI {
                        if amount <= obs.remaining_milli {
                            valid.push(Action::Invest(s, amount));
                        }
                    }
                    valid.push(Action::Pause(s));
                    valid.push(Action::Stop(s));
                }
            }
        }
        valid.push(Action::Finish);
        valid
    }

    pub fn step(&mut self, action: Action) -> Result<(Observation, StepInfo), String> {
        if self.done {
            return Err("episode already done".to_string());
        }
        let (question_id, chunks, scan_order) = {
            let q = self.question.as_ref().expect("reset before step");
            (q.id.clone(), q.chunks.clone(), q.scan_order.clone())
        };
        let mut obs = self.obs.clone().expect("reset before step");

        let mut gained = [0u8; STRATEGY_COUNT];
        let cost: Amount;
        match action {
            Action::Invest(s, amount) => {
                if s >= 2 {
                    return Err(format!(
                        "strategy {s} (deep/LLM) has no frozen fixture data — masked"
                    ));
                }
                if !INVEST_AMOUNTS_MILLI.contains(&amount) || amount > obs.remaining_milli {
                    return Err(format!("invalid invest amount {amount}"));
                }
                match obs.statuses[s] {
                    Status::Paused | Status::Stopped => {
                        return Err("strategy not investable".to_string());
                    }
                    _ => {}
                }
                let order: &[String] = if s == 0 && !scan_order.is_empty() {
                    &scan_order
                } else {
                    &chunks
                };
                let res_key = self.next_key("res");
                let reservation = self
                    .ledger
                    .reserve(&question_id, "exec", amount, &res_key)
                    .map_err(|e| e.to_string())?;
                let mut spent: Amount = 0;
                let cursor = &mut self.cursors[s];
                let before_hits = self.hits_by[s];
                while spent < amount && *cursor < order.len() {
                    let chunk = &order[*cursor];
                    *cursor += 1;
                    let answer = self
                        .replay
                        .as_ref()
                        .expect("reset loads the replay")
                        .analyze("scan", chunk, "")
                        .map_err(|e| e.to_string())?;
                    spent += 1_000; // tariff scan
                    if answer.choice == "fynd" && self.found.insert(chunk.clone()) {
                        self.hits_by[s] += 1;
                    }
                }
                let settle_key = self.next_key("settle");
                self.ledger
                    .settle(reservation, spent, &settle_key)
                    .map_err(|e| e.to_string())?;
                gained[s] = self.hits_by[s].saturating_sub(before_hits);
                obs.tiers = self.tiers();
                obs.found = (self.found.len() as u8).min(255);
                obs.spent_milli[s] += spent;
                obs.remaining_milli -= spent;
                obs.bracket = budget_bracket(obs.remaining_milli);
                obs.statuses[s] = Status::Active;
                obs.steps += 1;
                self.spent_milli[s] += spent;
                self.remaining_milli = obs.remaining_milli;
                self.steps = obs.steps;
                cost = spent;
                self.obs = Some(obs.clone());
                if obs.remaining_milli < MIN_INVEST_MILLI {
                    let (_, mut info) = self.finish("budget exhausted")?;
                    info.gained_tiers = gained;
                    info.cost_milli = cost;
                    info.reward_milli -= cost as i64;
                    let obs_final = self.obs.clone().expect("finish sets obs");
                    return Ok((obs_final, info));
                }
                if obs.steps >= self.max_steps {
                    let (_, mut info) = self.finish("max steps")?;
                    info.gained_tiers = gained;
                    info.cost_milli = cost;
                    info.reward_milli -= cost as i64;
                    let obs_final = self.obs.clone().expect("finish sets obs");
                    return Ok((obs_final, info));
                }
                Ok((
                    obs,
                    StepInfo {
                        reward_milli: -(cost as i64),
                        gained_tiers: gained,
                        cost_milli: cost,
                        done: false,
                        reason: String::new(),
                        ledger_events_added: 0,
                    },
                ))
            }
            Action::Pause(s) => {
                obs.statuses[s] = Status::Paused;
                obs.steps += 1;
                self.steps = obs.steps;
                self.obs = Some(obs.clone());
                Ok((
                    obs,
                    StepInfo {
                        reward_milli: 0,
                        gained_tiers: [0; STRATEGY_COUNT],
                        cost_milli: 0,
                        done: false,
                        reason: String::new(),
                        ledger_events_added: 0,
                    },
                ))
            }
            Action::Stop(s) => {
                obs.statuses[s] = Status::Stopped;
                obs.steps += 1;
                self.steps = obs.steps;
                self.obs = Some(obs.clone());
                Ok((
                    obs,
                    StepInfo {
                        reward_milli: 0,
                        gained_tiers: [0; STRATEGY_COUNT],
                        cost_milli: 0,
                        done: false,
                        reason: String::new(),
                        ledger_events_added: 0,
                    },
                ))
            }
            Action::Finish => self.finish("finish"),
        }
    }
}

// ---------------------------------------------------------------------------
// Harness: episode loop, evaluation, bench loading

use crate::agent::Policy;
use crate::bench::load_bench_file;
use crate::train::EpisodeReport;

/// Run one episode with a fresh env; reported reward is the net return
/// (sum of per-step rewards — same accounting identity as the synthetic
/// env).
pub fn run_episode_real(
    env: &mut RealEnv,
    policy: &mut dyn Policy,
    q: &RealQuestion,
    question_index: u64,
) -> EpisodeReport {
    env.reset(q).expect("valid real question");
    policy.episode_start(
        &crate::env::Question {
            id: q.id.clone(),
            qtype: q.qtype,
            budget_milli: q.budget_milli,
        },
        question_index,
    );
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
                question_id: q.id.clone(),
                qtype: q.qtype,
                steps: obs.steps,
                reward_milli: total_reward,
                spent_milli: obs.spent_milli.iter().sum(),
                reason: info.reason,
            };
        }
    }
}

/// Mean net reward over real questions. Baselines are deterministic; a
/// learner must be in eval mode.
pub fn evaluate_real(
    env: &mut RealEnv,
    policy: &mut dyn Policy,
    questions: &[RealQuestion],
) -> f64 {
    let mut total = 0.0;
    for (i, q) in questions.iter().enumerate() {
        total += run_episode_real(env, policy, q, i as u64).reward_milli as f64;
    }
    total / questions.len() as f64
}

/// Load the frozen real bench as v2 RealQuestions: bench JSON plus the
/// per-question replay fixtures. Budget per question is a configurable
/// constant (200 coins: enough for the similarity scanner on every
/// question, not enough for document order on the big ones — the
/// scarcity the budget manager is supposed to handle).
pub const REAL_BUDGET_PER_QUESTION_MILLI: Amount = 200_000;
pub const REAL_BASE_REWARD_MILLI: Amount = 100_000;

pub fn load_real_bench(bench_path: &str, fixtures_dir: &str) -> Result<Vec<RealQuestion>, String> {
    let bench = load_bench_file(bench_path)?;
    let mut out = Vec::new();
    for q in &bench.questions {
        let fixture_source = std::fs::read_to_string(format!("{fixtures_dir}/{}.json", q.view.id))
            .map_err(|e| format!("fixture for {}: {e}", q.view.id))?;
        out.push(RealQuestion {
            id: q.view.id.clone(),
            qtype: observable_qtype(q.view.chunks.len()),
            chunks: q.view.chunks.clone(),
            scan_order: q.view.scan_order.clone(),
            required: q.view.required_coverage,
            evidence: q.evidence.clone(),
            budget_milli: REAL_BUDGET_PER_QUESTION_MILLI,
            fixture_source,
        });
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// Real baselines: the same three simple rules as the synthetic baselines,
// but they stop on the real progress signal — new findings — which the
// tier quantization (0..4) cannot express.

#[derive(Default)]
struct RealMem {
    question_id: String,
    last_invested: Option<usize>,
    prev_found: u8,
    no_gain: u8,
    no_gain_by: [u8; 2],
    next: usize,
    est: [f64; 2],
}

impl RealMem {
    fn begin(&mut self, question: &crate::env::Question) {
        self.question_id = question.id.clone();
        self.last_invested = None;
        self.prev_found = 0;
        self.no_gain = 0;
        self.no_gain_by = [0; 2];
        self.next = 0;
        // Optimistic prior: 1 hit per 5000 milli until observed.
        self.est = [1.0 / 5_000.0; 2];
    }

    /// New findings since the previous decision; 0 if not investing yet.
    fn observe(&mut self, obs: &Observation) -> u8 {
        if self.last_invested.is_some() {
            let gain = obs.found.saturating_sub(self.prev_found);
            self.prev_found = obs.found;
            gain
        } else {
            0
        }
    }
}

/// Equal split over the real strategies: round-robin 5 coins A/B until
/// three consecutive investments yield no new findings.
pub struct RealEqualSplitPolicy {
    mem: RealMem,
}

impl RealEqualSplitPolicy {
    pub fn new() -> Self {
        Self {
            mem: RealMem::default(),
        }
    }
}

impl Policy for RealEqualSplitPolicy {
    fn name(&self) -> &'static str {
        "real-equal-split"
    }

    fn episode_start(&mut self, question: &crate::env::Question, _question_index: u64) {
        self.mem.begin(question);
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if self.mem.question_id != obs.question_id {
            self.mem.begin(&crate::env::Question {
                id: obs.question_id.clone(),
                qtype: obs.qtype,
                budget_milli: obs.remaining_milli,
            });
        }
        let gain = self.mem.observe(obs);
        if self.mem.last_invested.is_some() {
            if gain == 0 {
                self.mem.no_gain += 1;
            } else {
                self.mem.no_gain = 0;
            }
        }
        if self.mem.no_gain >= 3 {
            return Action::Finish;
        }
        for _ in 0..2 {
            let s = self.mem.next;
            self.mem.next = (s + 1) % 2;
            if valid.contains(&Action::Invest(s, 5_000)) {
                self.mem.last_invested = Some(s);
                self.mem.prev_found = obs.found;
                return Action::Invest(s, 5_000);
            }
        }
        Action::Finish
    }
}

/// Sequential priority over the real strategies: all-in on the first
/// strategy until three no-finding investments, then the second, then
/// finish. `first` picks the priority (0 = similarity scan first).
pub struct RealSequentialPolicy {
    mem: RealMem,
    first: usize,
}

impl RealSequentialPolicy {
    pub fn new(first: usize) -> Self {
        Self {
            mem: RealMem::default(),
            first,
        }
    }
}

impl Policy for RealSequentialPolicy {
    fn name(&self) -> &'static str {
        "real-sequential"
    }

    fn episode_start(&mut self, question: &crate::env::Question, _question_index: u64) {
        self.mem.begin(question);
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if self.mem.question_id != obs.question_id {
            self.mem.begin(&crate::env::Question {
                id: obs.question_id.clone(),
                qtype: obs.qtype,
                budget_milli: obs.remaining_milli,
            });
        }
        let gain = self.mem.observe(obs);
        if let Some(s) = self.mem.last_invested {
            if gain == 0 {
                self.mem.no_gain_by[s] += 1;
                if self.mem.no_gain_by[s] >= 3 {
                    self.mem.next = s + 1;
                }
            } else {
                self.mem.no_gain_by[s] = 0;
            }
        }
        // Priority order: [first, 1 - first].
        for candidate in [self.first, 1 - self.first] {
            if candidate >= self.mem.next && valid.contains(&Action::Invest(candidate, 5_000)) {
                self.mem.last_invested = Some(candidate);
                self.mem.prev_found = obs.found;
                return Action::Invest(candidate, 5_000);
            }
        }
        Action::Finish
    }
}

/// Heuristic adaptive over the real strategies: greedy on the observed
/// marginal findings per coin (EMA per strategy, optimistic prior).
pub struct RealAdaptivePolicy {
    mem: RealMem,
}

impl RealAdaptivePolicy {
    pub fn new() -> Self {
        Self {
            mem: RealMem::default(),
        }
    }
}

impl Policy for RealAdaptivePolicy {
    fn name(&self) -> &'static str {
        "real-adaptive"
    }

    fn episode_start(&mut self, question: &crate::env::Question, _question_index: u64) {
        self.mem.begin(question);
    }

    fn act(&mut self, obs: &Observation, valid: &[Action]) -> Action {
        if self.mem.question_id != obs.question_id {
            self.mem.begin(&crate::env::Question {
                id: obs.question_id.clone(),
                qtype: obs.qtype,
                budget_milli: obs.remaining_milli,
            });
        }
        if let Some(s) = self.mem.last_invested {
            let gain = obs.found.saturating_sub(self.mem.prev_found);
            if gain == 0 {
                self.mem.no_gain += 1;
            } else {
                self.mem.no_gain = 0;
            }
            let sample = gain as f64 / 5_000.0;
            let est = self.mem.est[s];
            self.mem.est[s] = 0.5 * est + 0.5 * sample;
        }
        if self.mem.no_gain >= 3 {
            return Action::Finish;
        }
        let mut best: Option<(usize, f64)> = None;
        for s in 0..2 {
            if !valid.contains(&Action::Invest(s, 5_000)) {
                continue;
            }
            let est = self.mem.est[s];
            if best.map_or(true, |(_, be)| est > be) {
                best = Some((s, est));
            }
        }
        match best {
            Some((s, est)) if est > 0.0 => {
                self.mem.last_invested = Some(s);
                self.mem.prev_found = obs.found;
                Action::Invest(s, 5_000)
            }
            _ => Action::Finish,
        }
    }
}
