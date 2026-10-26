//! The v2 gym environment: a budget-manager MDP over strategy segments.
//!
//! Design notes ([`docs/SWE_Sweycoins_v2.md`](../../docs/SWE_Sweycoins_v2.md)):
//!
//! - Decision-epoch MDP: one `step` = one budget decision. The synthetic
//!   segment consumes exactly the granted amount (a fixed-cost segment;
//!   the real environment settles actual cost from the ledger).
//! - The state is deliberately small and discretizable (question type,
//!   budget bracket, per-strategy progress tier) so an exact DP oracle
//!   exists and the learner can stay tabular — the v1 lesson: match
//!   policy capacity to signal strength.
//! - Sparse terminal reward (`difficulty x verified_quality x base - cost`)
//!   — the v1 lesson: episodic credit beat myopic shaping (84-210 vs
//!   325/500).
//! - Every milli flows through the ledger; positive rewards land in the
//!   virtual reward pool that can never be spent (ledger invariant 4),
//!   so training can never inflate the execution budget.
//!
//! Deterministic: same (question, policy) always produces the same
//! trajectory. The quality model (the facit) is never part of the
//! observation.

use crate::ledger::{Amount, Ledger, LedgerError};

pub const STRATEGY_COUNT: usize = 3; // A retrieval/graph, B JEV, C narrative LLM
pub const TIER_MAX: u8 = 4;
pub const TIER_LEVELS: u8 = TIER_MAX + 1; // 0..=4
pub const BRACKETS: u8 = 4;
pub const MAX_STEPS: u32 = 32;
pub const MIN_INVEST_MILLI: Amount = 1_000;

/// Discrete investment amounts (spec 5.2: 1, 5, 10, 20 Sweycoins).
pub const INVEST_AMOUNTS_MILLI: [Amount; 4] = [1_000, 5_000, 10_000, 20_000];

/// One question for the budget manager. The facit is never exposed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Question {
    pub id: String,
    pub qtype: u8,
    pub budget_milli: Amount,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    Idle,
    Active,
    Paused,
    Stopped,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Observation {
    pub question_id: String,
    pub qtype: u8,
    pub remaining_milli: Amount,
    pub bracket: u8,
    pub tiers: [u8; STRATEGY_COUNT],
    pub statuses: [Status; STRATEGY_COUNT],
    pub spent_milli: [Amount; STRATEGY_COUNT],
    pub steps: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Invest(usize, Amount),
    Pause(usize),
    Stop(usize),
    Finish,
}

pub const ACTION_COUNT: usize = 3 * 4 + 3 + 3 + 1; // invest x12, pause x3, stop x3, finish

pub fn action_index(action: Action) -> usize {
    match action {
        Action::Invest(s, amount) => s * 4 + amount_index(amount).expect("valid invest amount"),
        Action::Pause(s) => 12 + s,
        Action::Stop(s) => 15 + s,
        Action::Finish => 18,
    }
}

pub fn amount_index(milli: Amount) -> Option<usize> {
    INVEST_AMOUNTS_MILLI.iter().position(|a| *a == milli)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StepInfo {
    pub reward_milli: i64,
    pub gained_tiers: [u8; STRATEGY_COUNT],
    pub cost_milli: Amount,
    pub done: bool,
    pub reason: String,
    pub ledger_events_added: usize,
}

/// Strategy economics per question type: cost (in milli) to advance from
/// tier `t` to tier `t+1`, and the quality contributed at full progress.
/// Quality of tier `t` is `cap_quality * t / TIER_MAX`.
#[derive(Clone, Copy, Debug)]
pub struct StrategyProfile {
    /// `tier_cost_milli[type]` is the per-tier advance cost list, length TIER_MAX.
    pub tier_cost_milli: [[Amount; TIER_MAX as usize]; 4],
    pub cap_quality: f64,
}

#[derive(Clone, Copy, Debug)]
pub struct TypeSpec {
    pub difficulty: f64,
    pub strategies: [StrategyProfile; STRATEGY_COUNT],
}

#[derive(Clone, Debug)]
pub struct EnvConfig {
    pub types: [TypeSpec; 4],
    pub base_reward_milli: Amount,
}

/// Default synthetic world: four question types with distinct optimal
/// budget allocations, diminishing per-tier returns, and strategy caps so
/// no single strategy dominates. Tuned so the oracle beats every simple
/// baseline by a wide margin (calibration gate, docs/SWE_Sweycoins_v2.md 9).
pub fn default_config() -> EnvConfig {
    EnvConfig {
        base_reward_milli: 100_000,
        types: [
            TypeSpec {
                // t0: cheap single-strategy questions; C alone is enough.
                difficulty: 1.0,
                strategies: [
                    StrategyProfile {
                        tier_cost_milli: [
                            [1_000, 2_000, 3_000, 4_000],
                            [4_000, 8_000, 12_000, 16_000],
                            [2_000, 4_000, 6_000, 8_000],
                            [2_000, 4_000, 6_000, 8_000],
                        ],
                        cap_quality: 0.5,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [4_000, 8_000, 12_000, 16_000],
                            [4_000, 8_000, 12_000, 16_000],
                            [4_000, 8_000, 12_000, 16_000],
                            [4_000, 8_000, 12_000, 16_000],
                        ],
                        cap_quality: 0.6,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [2_000, 4_000, 6_000, 8_000],
                            [3_000, 6_000, 9_000, 12_000],
                            [3_000, 6_000, 9_000, 12_000],
                            [1_000, 2_000, 3_000, 4_000],
                        ],
                        cap_quality: 1.0,
                    },
                ],
            },
            TypeSpec {
                // t1: A-heavy mix: retrieval + JEV evidence; C too expensive.
                difficulty: 1.5,
                strategies: [
                    StrategyProfile {
                        tier_cost_milli: [
                            [1_000, 2_000, 3_000, 4_000],
                            [1_000, 2_000, 3_000, 4_000],
                            [4_000, 8_000, 12_000, 16_000],
                            [8_000, 16_000, 24_000, 32_000],
                        ],
                        cap_quality: 0.5,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [2_000, 4_000, 6_000, 8_000],
                            [2_000, 4_000, 6_000, 8_000],
                            [1_000, 2_000, 3_000, 4_000],
                            [8_000, 16_000, 24_000, 32_000],
                        ],
                        cap_quality: 0.6,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [3_000, 6_000, 9_000, 12_000],
                            [3_000, 6_000, 9_000, 12_000],
                            [3_000, 6_000, 9_000, 12_000],
                            [1_000, 2_000, 3_000, 4_000],
                        ],
                        cap_quality: 1.0,
                    },
                ],
            },
            TypeSpec {
                // t2: B-heavy mix: JEV carries, retrieval helps.
                difficulty: 1.5,
                strategies: [
                    StrategyProfile {
                        tier_cost_milli: [
                            [4_000, 8_000, 12_000, 16_000],
                            [4_000, 8_000, 12_000, 16_000],
                            [4_000, 8_000, 12_000, 16_000],
                            [8_000, 16_000, 24_000, 32_000],
                        ],
                        cap_quality: 0.5,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [1_000, 2_000, 3_000, 4_000],
                            [2_000, 4_000, 6_000, 8_000],
                            [1_000, 2_000, 3_000, 4_000],
                            [8_000, 16_000, 24_000, 32_000],
                        ],
                        cap_quality: 0.6,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [3_000, 6_000, 9_000, 12_000],
                            [3_000, 6_000, 9_000, 12_000],
                            [3_000, 6_000, 9_000, 12_000],
                            [1_000, 2_000, 3_000, 4_000],
                        ],
                        cap_quality: 1.0,
                    },
                ],
            },
            TypeSpec {
                // t3: only the narrative LLM reaches the target; retrieval
                // and JEV are nearly useless (their rates are prohibitive).
                difficulty: 2.0,
                strategies: [
                    StrategyProfile {
                        tier_cost_milli: [
                            [8_000, 16_000, 24_000, 32_000],
                            [8_000, 16_000, 24_000, 32_000],
                            [8_000, 16_000, 24_000, 32_000],
                            [8_000, 16_000, 24_000, 32_000],
                        ],
                        cap_quality: 0.5,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [8_000, 16_000, 24_000, 32_000],
                            [8_000, 16_000, 24_000, 32_000],
                            [8_000, 16_000, 24_000, 32_000],
                            [8_000, 16_000, 24_000, 32_000],
                        ],
                        cap_quality: 0.6,
                    },
                    StrategyProfile {
                        tier_cost_milli: [
                            [1_000, 2_000, 3_000, 4_000],
                            [1_000, 2_000, 3_000, 4_000],
                            [1_000, 2_000, 3_000, 4_000],
                            [1_000, 2_000, 3_000, 4_000],
                        ],
                        cap_quality: 1.0,
                    },
                ],
            },
        ],
    }
}

/// Verified quality of a progress state: sum of per-strategy quality
/// contributions, capped at 1.0. In the synthetic world the quality model
/// is the facit; it is evaluated only at episode end, never observed.
pub fn verified_quality(config: &EnvConfig, qtype: u8, tiers: &[u8; STRATEGY_COUNT]) -> f64 {
    let type_spec = &config.types[qtype as usize];
    let mut q = 0.0;
    for s in 0..STRATEGY_COUNT {
        q += type_spec.strategies[s].cap_quality * tiers[s] as f64 / TIER_MAX as f64;
    }
    q.min(1.0)
}

/// Quality reward at episode end: `difficulty x verified_quality x base`
/// (no cost — cost is debited per step, which keeps the tier state Markov).
pub fn quality_reward(config: &EnvConfig, qtype: u8, tiers: &[u8; STRATEGY_COUNT]) -> i64 {
    let type_spec = &config.types[qtype as usize];
    let value = (type_spec.difficulty * verified_quality(config, qtype, tiers))
        * config.base_reward_milli as f64;
    value.round() as i64
}

/// Net terminal reward of a trajectory (spec 6):
/// `difficulty x verified_quality x base_reward - total_cost`.
/// Identical to the sum of the per-step rewards the env emits
/// (`-cost` per investment, `quality_reward` at the end).
pub fn terminal_reward(
    config: &EnvConfig,
    qtype: u8,
    tiers: &[u8; STRATEGY_COUNT],
    spent_milli: Amount,
) -> i64 {
    quality_reward(config, qtype, tiers) - spent_milli as i64
}

/// Tiers gained by investing `invest_milli` in strategy `s` from `tier`:
/// whole tiers are paid in sequence, the leftover is overhead (a metered
/// segment that overshoots its quota). Deterministic.
pub fn gain_tiers(config: &EnvConfig, qtype: u8, s: usize, tier: u8, invest_milli: Amount) -> u8 {
    let costs = &config.types[qtype as usize].strategies[s].tier_cost_milli[qtype as usize];
    let mut left = invest_milli;
    let mut gained = 0;
    let mut t = tier;
    while t < TIER_MAX {
        let cost = costs[t as usize];
        if left < cost {
            break;
        }
        left -= cost;
        t += 1;
        gained += 1;
    }
    gained
}

/// Budget bracket: coarse quantization of remaining budget for the learner
/// state (docs/SWE_Sweycoins_v2.md 5).
pub fn budget_bracket(remaining_milli: Amount) -> u8 {
    match remaining_milli {
        r if r < 20_000 => 0,
        r if r < 50_000 => 1,
        r if r < 80_000 => 2,
        _ => 3,
    }
}

#[derive(Debug)]
pub enum EnvError {
    NotReset,
    InvalidAction(Action, String),
    InvalidQuestion(String),
    Ledger(LedgerError),
}

impl std::fmt::Display for EnvError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotReset => write!(f, "env not reset"),
            Self::InvalidAction(action, why) => {
                write!(f, "invalid action {action:?}: {why}")
            }
            Self::InvalidQuestion(why) => write!(f, "invalid question: {why}"),
            Self::Ledger(e) => write!(f, "ledger error: {e}"),
        }
    }
}

impl std::error::Error for EnvError {}

pub trait SweEnv {
    fn config(&self) -> &EnvConfig;
    fn ledger(&self) -> &Ledger;
    fn observation(&self) -> &Observation;
    fn reset(&mut self, question: &Question) -> Result<Observation, EnvError>;
    fn step(&mut self, action: Action) -> Result<(Observation, StepInfo), EnvError>;
    fn valid_actions(&self) -> Vec<Action>;
}

/// Deterministic in-memory environment: each `step` books the granted
/// amount through the ledger and advances strategy tiers per the config.
pub struct SyntheticEnv {
    config: EnvConfig,
    ledger: Ledger,
    obs: Option<Observation>,
    question: Option<Question>,
    done: bool,
    key_seq: u64,
}

impl SyntheticEnv {
    pub fn new(config: EnvConfig) -> Self {
        Self {
            config,
            ledger: Ledger::new(),
            obs: None,
            question: None,
            done: false,
            key_seq: 0,
        }
    }

    fn next_key(&mut self, label: &str) -> String {
        self.key_seq += 1;
        format!("{label}:{}", self.key_seq)
    }

    fn finish(&mut self, reason: &str) -> Result<(Observation, StepInfo), EnvError> {
        let obs = self.obs.clone().expect("reset before finish");
        let reward = quality_reward(&self.config, obs.qtype, &obs.tiers);
        let before = self.ledger.events().len();
        if reward > 0 {
            let run_id = obs.question_id.clone();
            let key = self.next_key("reward");
            self.ledger
                .reward(&run_id, "training", reward as Amount, &key)
                .map_err(EnvError::Ledger)?;
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
                ledger_events_added: self.ledger.events().len() - before,
            },
        ))
    }
}

impl SweEnv for SyntheticEnv {
    fn config(&self) -> &EnvConfig {
        &self.config
    }

    fn ledger(&self) -> &Ledger {
        &self.ledger
    }

    fn observation(&self) -> &Observation {
        self.obs.as_ref().expect("reset before observe")
    }

    fn reset(&mut self, question: &Question) -> Result<Observation, EnvError> {
        if question.qtype as usize >= self.config.types.len() {
            return Err(EnvError::InvalidQuestion(format!(
                "unknown question type {}",
                question.qtype
            )));
        }
        if question.budget_milli < MIN_INVEST_MILLI || question.budget_milli % 1_000 != 0 {
            return Err(EnvError::InvalidQuestion(format!(
                "budget must be a coin multiple >= {MIN_INVEST_MILLI}, got {}",
                question.budget_milli
            )));
        }
        self.ledger = Ledger::new();
        self.key_seq = 0;
        let alloc_key = self.next_key("alloc");
        self.ledger
            .allocate(&question.id, "exec", question.budget_milli, &alloc_key)
            .map_err(EnvError::Ledger)?;
        self.question = Some(question.clone());
        self.done = false;
        let obs = Observation {
            question_id: question.id.clone(),
            qtype: question.qtype,
            remaining_milli: question.budget_milli,
            bracket: budget_bracket(question.budget_milli),
            tiers: [0; STRATEGY_COUNT],
            statuses: [Status::Idle; STRATEGY_COUNT],
            spent_milli: [0; STRATEGY_COUNT],
            steps: 0,
        };
        self.obs = Some(obs.clone());
        Ok(obs)
    }

    fn step(&mut self, action: Action) -> Result<(Observation, StepInfo), EnvError> {
        if self.done {
            return Err(EnvError::InvalidAction(
                action,
                "episode already done".into(),
            ));
        }
        let question = self.question.clone().ok_or(EnvError::NotReset)?;
        let mut obs = self.obs.clone().ok_or(EnvError::NotReset)?;

        let mut gained = [0u8; STRATEGY_COUNT];
        let cost: Amount;
        match action {
            Action::Invest(s, amount) => {
                if s >= STRATEGY_COUNT {
                    return Err(EnvError::InvalidAction(action, "bad strategy".into()));
                }
                if amount_index(amount).is_none() {
                    return Err(EnvError::InvalidAction(action, "bad amount".into()));
                }
                if amount > obs.remaining_milli {
                    return Err(EnvError::InvalidAction(action, "exceeds remaining".into()));
                }
                match obs.statuses[s] {
                    Status::Paused | Status::Stopped => {
                        return Err(EnvError::InvalidAction(
                            action,
                            "strategy not investable".into(),
                        ));
                    }
                    _ => {}
                }
                let before = self.ledger.events().len();
                let res_key = self.next_key("res");
                let reservation = self
                    .ledger
                    .reserve(&question.id, "exec", amount, &res_key)
                    .map_err(EnvError::Ledger)?;
                let settle_key = self.next_key("settle");
                self.ledger
                    .settle(reservation, amount, &settle_key)
                    .map_err(EnvError::Ledger)?;
                let gained_here = gain_tiers(&self.config, obs.qtype, s, obs.tiers[s], amount);
                gained[s] = gained_here;
                obs.tiers[s] = (obs.tiers[s] + gained_here).min(TIER_MAX);
                obs.spent_milli[s] += amount;
                obs.remaining_milli -= amount;
                obs.bracket = budget_bracket(obs.remaining_milli);
                obs.statuses[s] = Status::Active;
                cost = amount;
                obs.steps += 1;
                self.obs = Some(obs.clone());
                let ledger_events_added = self.ledger.events().len() - before;
                if obs.remaining_milli < MIN_INVEST_MILLI {
                    let (_, mut info) = self.finish("budget exhausted")?;
                    info.gained_tiers = gained;
                    info.cost_milli = cost;
                    // Debit this investment plus the terminal quality
                    // reward, so the step stream sums to the net return.
                    info.reward_milli -= cost as i64;
                    info.ledger_events_added += ledger_events_added;
                    let obs_final = self.obs.clone().expect("finish sets obs");
                    return Ok((obs_final, info));
                }
                if obs.steps >= MAX_STEPS {
                    let (_, mut info) = self.finish("max steps")?;
                    info.gained_tiers = gained;
                    info.cost_milli = cost;
                    info.reward_milli -= cost as i64;
                    info.ledger_events_added += ledger_events_added;
                    let obs_final = self.obs.clone().expect("finish sets obs");
                    return Ok((obs_final, info));
                }
                Ok((
                    obs,
                    StepInfo {
                        // Per-step cost debit: the tier state is Markov,
                        // unlike the net terminal formula (v2 learner fix).
                        reward_milli: -(amount as i64),
                        gained_tiers: gained,
                        cost_milli: cost,
                        done: false,
                        reason: String::new(),
                        ledger_events_added,
                    },
                ))
            }
            Action::Pause(s) => {
                obs.statuses[s] = Status::Paused;
                obs.steps += 1;
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

    fn valid_actions(&self) -> Vec<Action> {
        let obs = match &self.obs {
            Some(o) if !self.done => o,
            _ => return vec![],
        };
        let mut valid = Vec::new();
        for s in 0..STRATEGY_COUNT {
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
}
