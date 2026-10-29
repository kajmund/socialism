//! RealEnv: the v2 gym over the frozen real legal bench — the common
//! observation interface for real workflows (docs/SWE_Sweycoins_v2.md 14).
//!
//! Two genuinely different capabilities with frozen, reproducible data:
//!
//! - **A = retrieval**: expands the candidate pool in similarity order
//!   (tariff `lookup`, 50 milli/chunk). Retrieval alone produces NO
//!   verified evidence — it changes the value of later JEV calls, the
//!   real delayed-return structure.
//! - **B = JEV**: verifies the top unverified chunk of the pool (tariff
//!   `scan`, 1 coin/call) against the frozen 2019 answers. Its marginal
//!   utility depends on the pool A has surfaced.
//! - **C = deep/LLM**: masked — the frozen fixtures carry no deep
//!   answers (documented limitation; capturing them is the next step).
//!
//! Observation: the facit-free interface the budget manager must be able
//! to reason from (docs 14): spent per capability, remaining budget,
//! new evidence count, recent findings per 100 verification calls,
//! last verification confidence, pool state. Quality (hits/required) is
//! revealed only at episode end, never in the observation.

use std::collections::HashSet;

use crate::agent::Policy;
use crate::bench::load_bench_file;
use crate::env::{
    budget_bracket, Action, Observation, Status, StepInfo, INVEST_AMOUNTS_MILLI, MIN_INVEST_MILLI,
    STRATEGY_COUNT, TIER_MAX,
};
use crate::ledger::{Amount, Ledger};
use crate::provider::{ReplayProvider, ResearchProvider};
use crate::train::EpisodeReport;

/// Retrieval lookup tariff: 0.05 coin per surfaced chunk (the SSR-anchor
/// / embedding-side cost; the index itself is already amortized).
pub const LOOKUP_MILLI: Amount = 50;
/// JEV verification tariff (matches the frozen bench's `scan` tariff).
pub const SCAN_MILLI: Amount = 1_000;
/// Rolling window for the observable marginal-utility signal.
pub const HIT_RATE_WINDOW: usize = 20;

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

/// Document prefix of a chunk id ("Avtal_47_Programvarulicensavtal:25"
/// -> "Avtal_47_Programvarulicensavtal"): the facit-free document
/// provenance encoded in the corpus chunk ids.
fn doc_prefix(chunk_id: &str) -> &str {
    chunk_id.split(':').next().unwrap_or(chunk_id)
}

/// One real question for the budget manager: the facit-free view plus
/// the facit (evaluator only, same split as bench.rs).
#[derive(Clone)]
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
    pool_cursor: usize,   // retrieval: chunks surfaced (A)
    verify_cursor: usize, // JEV: chunks verified (B)
    hits_by: [u8; 2],
    found: HashSet<String>,
    recent_outcomes: Vec<bool>,
    last_score_bp: u32,
    extension_baseline: usize,
    zero_streak: u8,
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
            pool_cursor: 0,
            verify_cursor: 0,
            hits_by: [0, 0],
            found: HashSet::new(),
            recent_outcomes: Vec::new(),
            last_score_bp: 0,
            extension_baseline: 0,
            zero_streak: 0,
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
        let question = self.question.as_ref().expect("reset before tiers");
        let pool_quintile = if question.chunks.is_empty() {
            0
        } else {
            (self.pool_cursor as u64 * TIER_MAX as u64 / question.chunks.len() as u64) as u8
        };
        [
            pool_quintile.min(TIER_MAX),
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

    fn recent_hit_rate_bp(&self) -> u32 {
        let n = self.recent_outcomes.len();
        if n == 0 {
            return 0;
        }
        let hits: usize = self.recent_outcomes.iter().filter(|h| **h).count();
        (10_000 * hits / n) as u32
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

    /// Verified quality of the current state (facit-evaluated; used by
    /// the dataset recorder for the terminal field only).
    pub fn terminal_quality(&self) -> f64 {
        self.quality()
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
        self.pool_cursor = 0;
        self.verify_cursor = 0;
        self.hits_by = [0, 0];
        self.found = HashSet::new();
        self.recent_outcomes = Vec::new();
        self.last_score_bp = 0;
        self.extension_baseline = 0;
        self.zero_streak = 0;
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
            new_evidence: 0,
            contradictions: 0,
            recent_hit_rate_bp: 0,
            last_score_bp: 0,
            pool_scanned: 0,
            pool_total: q.chunks.len() as u32,
            pool_extension_yielded: 0,
            zero_hit_streak: 0,
            next_rank_bp: 0,
            docs_remaining: 0,
            docs_with_hits: 0,
            new_doc_hit: 0,
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
        let mut new_evidence = 0u8;
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
                let res_key = self.next_key("res");
                let reservation = self
                    .ledger
                    .reserve(&question_id, "exec", amount, &res_key)
                    .map_err(|e| e.to_string())?;
                let mut spent: Amount = 0;
                match s {
                    0 => {
                        // Retrieval: surface pool chunks in similarity order.
                        // A new extension resets the yield baseline: has
                        // this extension paid off in new evidence?
                        self.extension_baseline = self.found.len();
                        let per_chunk = LOOKUP_MILLI;
                        while spent + per_chunk <= amount && self.pool_cursor < chunks.len() {
                            self.pool_cursor += 1;
                            spent += per_chunk;
                        }
                    }
                    _ => {
                        // JEV: verify the top unverified chunk of the pool.
                        let order: &[String] = if !scan_order.is_empty() {
                            &scan_order
                        } else {
                            &chunks
                        };
                        let replay = self.replay.as_ref().expect("reset loads the replay");
                        while spent + SCAN_MILLI <= amount && self.verify_cursor < self.pool_cursor
                        {
                            let chunk = &order[self.verify_cursor];
                            self.verify_cursor += 1;
                            spent += SCAN_MILLI;
                            let answer = replay
                                .analyze("scan", chunk, "")
                                .map_err(|e| e.to_string())?;
                            self.last_score_bp = answer.score_bp;
                            let hit = answer.choice == "fynd";
                            if hit {
                                self.zero_streak = 0;
                            } else {
                                self.zero_streak = self.zero_streak.saturating_add(1);
                            }
                            self.recent_outcomes.push(hit);
                            if self.recent_outcomes.len() > HIT_RATE_WINDOW {
                                self.recent_outcomes.remove(0);
                            }
                            if hit && self.found.insert(chunk.clone()) {
                                self.hits_by[1] += 1;
                                new_evidence += 1;
                            }
                        }
                    }
                }
                let settle_key = self.next_key("settle");
                self.ledger
                    .settle(reservation, spent, &settle_key)
                    .map_err(|e| e.to_string())?;
                gained[s] = if s == 0 {
                    let before = obs.tiers[0];
                    let after = self.tiers()[0];
                    after.saturating_sub(before)
                } else {
                    0
                };
                obs.tiers = self.tiers();
                obs.found = (self.found.len() as u8).min(255);
                obs.new_evidence = new_evidence;
                obs.recent_hit_rate_bp = self.recent_hit_rate_bp();
                obs.last_score_bp = self.last_score_bp;
                obs.pool_scanned = self.pool_cursor as u32;
                obs.pool_extension_yielded = (self.found.len() > self.extension_baseline) as u8;
                obs.zero_hit_streak = self.zero_streak;
                // Rank progress: the next candidate's position in the
                // ranked list — the facit-free similarity-decay proxy.
                obs.next_rank_bp = if chunks.is_empty() {
                    0
                } else {
                    (10_000 * self.verify_cursor as u64 / chunks.len() as u64) as u32
                };
                // Document provenance, from chunk-id prefixes.
                let order: &[String] = if !scan_order.is_empty() {
                    &scan_order
                } else {
                    &chunks
                };
                let mut remaining_docs = std::collections::HashSet::new();
                for chunk in order.iter().take(self.pool_cursor).skip(self.verify_cursor) {
                    remaining_docs.insert(doc_prefix(chunk));
                }
                obs.docs_remaining = remaining_docs.len().min(255) as u8;
                let hit_docs: std::collections::HashSet<&str> =
                    self.found.iter().map(|c| doc_prefix(c)).collect();
                obs.docs_with_hits = hit_docs.len().min(255) as u8;
                obs.new_doc_hit = if new_evidence > 0 {
                    let before = hit_docs.len();
                    let mut extended = hit_docs;
                    extended.extend(
                        order
                            .iter()
                            .take(self.verify_cursor)
                            .skip(self.verify_cursor.saturating_sub(64))
                            .map(|c| doc_prefix(c)),
                    );
                    (extended.len() > before) as u8
                } else {
                    0
                };
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

/// Run one episode with a fresh env; reported reward is the net return.
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
// Real baselines for the two-capability benchmark

#[derive(Default)]
struct RealMem {
    question_id: String,
    last_invested: Option<usize>,
    prev_found: u8,
    no_gain: u8,
    next: usize,
    cycle_found: u8,
}

impl RealMem {
    fn begin(&mut self, question: &crate::env::Question) {
        self.question_id = question.id.clone();
        self.last_invested = None;
        self.prev_found = 0;
        self.no_gain = 0;
        self.next = 0;
        self.cycle_found = 0;
    }

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

/// The strong adaptive baseline — and the teacher policy for the
/// student POC. The rule is a pure function of the observation interface
/// (no hidden memory): behavior cloning can only imitate what the
/// observation determines, so the teacher must be observation-
/// deterministic by construction (measured: a memory-based variant
/// produced label conflicts — the same observation mapped to different
/// actions).
///
/// Rule: empty pool -> retrieve (A). Verifying (B) while the zero-find
/// streak is short. On a stall (streak >= 3): if the current pool
/// extension paid off in new evidence, extend again; if it paid
/// nothing, the productive region is exhausted — finish.
pub struct RealPipelinePolicy {
    mem: RealMem,
    /// Zero-find streak that triggers the stall decision (calls).
    pub stall_threshold: u8,
}

impl RealPipelinePolicy {
    pub fn new() -> Self {
        Self {
            mem: RealMem::default(),
            stall_threshold: 12,
        }
    }

    pub fn with_stall(threshold: u8) -> Self {
        Self {
            mem: RealMem::default(),
            stall_threshold: threshold,
        }
    }
}

impl Policy for RealPipelinePolicy {
    fn name(&self) -> &'static str {
        "real-pipeline-adaptive"
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
        if obs.pool_scanned == 0 {
            return Action::Invest(0, 1_000);
        }
        if obs.zero_hit_streak >= self.stall_threshold {
            let pool_full = obs.pool_scanned >= obs.pool_total;
            if obs.pool_extension_yielded == 1
                && !pool_full
                && valid.contains(&Action::Invest(0, 1_000))
            {
                return Action::Invest(0, 1_000);
            }
            return Action::Finish;
        }
        if valid.contains(&Action::Invest(1, 5_000)) {
            Action::Invest(1, 5_000)
        } else {
            Action::Finish
        }
    }
}

/// Equal split over the two capabilities: alternate A/B until three
/// consecutive B investments yield no new findings.
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
        if let Some(s) = self.mem.last_invested {
            if s == 1 && gain == 0 {
                self.mem.no_gain += 1;
            } else if s == 1 {
                self.mem.no_gain = 0;
            }
        }
        if self.mem.no_gain >= 3 {
            return Action::Finish;
        }
        for _ in 0..2 {
            let s = self.mem.next;
            self.mem.next = (s + 1) % 2;
            let amount = if s == 0 { 1_000 } else { 5_000 };
            if valid.contains(&Action::Invest(s, amount)) {
                self.mem.last_invested = Some(s);
                self.mem.prev_found = obs.found;
                return Action::Invest(s, amount);
            }
        }
        Action::Finish
    }
}
