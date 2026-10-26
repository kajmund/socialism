//! The real training dataset (docs/SWE_Sweycoins_v2.md 15): recorded
//! decision sequences over the frozen real bench — question features,
//! every investment decision with the full facit-free observation it
//! was made on, observed outcome, actual cost, and the final verified
//! quality. The facit appears in exactly one place: the terminal
//! quality field, never in the observations the policy acted on.
//!
//! A recorded trajectory shows what happened, not what would have
//! happened under a different investment — the dataset is experience
//! data (teacher demonstrations, offline-RL input), never a simulator.

use crate::agent::Policy;
use crate::env::{action_from_index, action_index, Action, Observation, Status};
use crate::ledger::Amount;
use crate::provider::json_escape;
use crate::real::{RealEnv, RealQuestion};
use swe_native::{parse_json_str, Json};

pub const DATASET_VERSION: u64 = 1;

#[derive(Clone, Debug, PartialEq)]
pub struct StepRecord {
    /// The full facit-free observation the decision was made on.
    pub obs: Observation,
    pub action: Action,
    pub cost_milli: Amount,
    pub reward_milli: i64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Trajectory {
    pub policy: String,
    pub seed: u64,
    pub question_id: String,
    pub qtype: u8,
    pub budget_milli: Amount,
    pub steps: Vec<StepRecord>,
    pub terminal_quality: f64,
    pub total_cost_milli: Amount,
    pub total_reward_milli: i64,
}

/// Record one episode: snapshot the observation before every decision,
/// the action taken, and the step's cost and reward.
pub fn record_episode(
    env: &mut RealEnv,
    policy: &mut dyn Policy,
    q: &RealQuestion,
    question_index: u64,
    policy_name: &str,
    seed: u64,
) -> Trajectory {
    env.reset(q).expect("valid real question");
    policy.episode_start(
        &crate::env::Question {
            id: q.id.clone(),
            qtype: q.qtype,
            budget_milli: q.budget_milli,
        },
        question_index,
    );
    let mut steps = Vec::new();
    let mut total_reward: i64 = 0;
    loop {
        let obs = env.observation().clone();
        let valid = env.valid_actions();
        let action = policy.act(&obs, &valid);
        let (_obs, info) = env.step(action).expect("policy picked a valid action");
        total_reward += info.reward_milli;
        policy.on_step(info.reward_milli);
        steps.push(StepRecord {
            obs,
            action,
            cost_milli: info.cost_milli,
            reward_milli: info.reward_milli,
        });
        if info.done {
            break;
        }
    }
    let spent = env.observation().spent_milli.iter().sum::<Amount>();
    Trajectory {
        policy: policy_name.to_string(),
        seed,
        question_id: q.id.clone(),
        qtype: q.qtype,
        budget_milli: q.budget_milli,
        steps,
        terminal_quality: env.terminal_quality(),
        total_cost_milli: spent,
        total_reward_milli: total_reward,
    }
}

// ---------------------------------------------------------------------------
// JSON serialization (same hand-rolled style as the fixture writer)

fn obs_to_json(obs: &Observation) -> String {
    let tiers = obs.tiers.map(|t| t.to_string()).join(",");
    let statuses = obs.statuses.map(|st| (st as u8).to_string()).join(",");
    let spent = obs.spent_milli.map(|s| s.to_string()).join(",");
    format!(
        r#"{{"question_id":"{}","qtype":{},"remaining_milli":{},"bracket":{},"tiers":[{}],"found":{},"new_evidence":{},"contradictions":{},"recent_hit_rate_bp":{},"last_score_bp":{},"pool_scanned":{},"pool_total":{},"statuses":[{}],"spent_milli":[{}],"steps":{}}}"#,
        json_escape(&obs.question_id),
        obs.qtype,
        obs.remaining_milli,
        obs.bracket,
        tiers,
        obs.found,
        obs.new_evidence,
        obs.contradictions,
        obs.recent_hit_rate_bp,
        obs.last_score_bp,
        obs.pool_scanned,
        obs.pool_total,
        statuses,
        spent,
        obs.steps,
    )
}

fn status_from_u8(v: u8) -> Result<Status, String> {
    match v {
        0 => Ok(Status::Idle),
        1 => Ok(Status::Active),
        2 => Ok(Status::Paused),
        _ => Ok(Status::Stopped),
    }
}

fn obs_from_json(json: &Json) -> Result<Observation, String> {
    let get = |key: &str| json.get(key).ok_or_else(|| format!("obs missing {key}"));
    let u8_at = |key: &str| -> Result<u8, String> {
        get(key)?
            .as_number()
            .and_then(|n| n.as_u64())
            .map(|v| v as u8)
            .ok_or_else(|| format!("obs field {key} not a number"))
    };
    let u32_at = |key: &str| -> Result<u32, String> {
        get(key)?
            .as_number()
            .and_then(|n| n.as_u64())
            .map(|v| v as u32)
            .ok_or_else(|| format!("obs field {key} not a number"))
    };
    let u64_at = |key: &str| -> Result<u64, String> {
        get(key)?
            .as_number()
            .and_then(|n| n.as_u64())
            .ok_or_else(|| format!("obs field {key} not a number"))
    };
    let arr = |key: &str| -> Result<Vec<u64>, String> {
        let a = get(key)?
            .as_array()
            .ok_or_else(|| format!("obs field {key} not an array"))?;
        a.iter()
            .map(|j| {
                j.as_number()
                    .and_then(|n| n.as_u64())
                    .ok_or_else(|| format!("obs field {key} entry not a number"))
            })
            .collect()
    };
    let tiers = arr("tiers")?;
    let statuses = arr("statuses")?;
    let spent = arr("spent_milli")?;
    Ok(Observation {
        question_id: get("question_id")?
            .as_str()
            .ok_or("obs question_id not a string")?
            .to_string(),
        qtype: u8_at("qtype")?,
        remaining_milli: u64_at("remaining_milli")?,
        bracket: u8_at("bracket")?,
        tiers: [tiers[0] as u8, tiers[1] as u8, tiers[2] as u8],
        found: u8_at("found")?,
        new_evidence: u8_at("new_evidence")?,
        contradictions: u8_at("contradictions")?,
        recent_hit_rate_bp: u32_at("recent_hit_rate_bp")?,
        last_score_bp: u32_at("last_score_bp")?,
        pool_scanned: u32_at("pool_scanned")?,
        pool_total: u32_at("pool_total")?,
        statuses: [
            status_from_u8(statuses[0] as u8)?,
            status_from_u8(statuses[1] as u8)?,
            status_from_u8(statuses[2] as u8)?,
        ],
        spent_milli: [spent[0], spent[1], spent[2]],
        steps: u32_at("steps")?,
    })
}

pub fn trajectory_to_json(t: &Trajectory) -> String {
    let steps: Vec<String> = t
        .steps
        .iter()
        .map(|s| {
            format!(
                r#"{{"obs":{},"action":{},"action_label":"{}","cost_milli":{},"reward_milli":{}}}"#,
                obs_to_json(&s.obs),
                action_index(s.action),
                json_escape(&format!("{:?}", s.action)),
                s.cost_milli,
                s.reward_milli,
            )
        })
        .collect();
    format!(
        r#"{{"policy":"{}","seed":{},"question_id":"{}","qtype":{},"budget_milli":{},"steps":[{}],"terminal_quality":{},"total_cost_milli":{},"total_reward_milli":{}}}"#,
        json_escape(&t.policy),
        t.seed,
        json_escape(&t.question_id),
        t.qtype,
        t.budget_milli,
        steps.join(","),
        t.terminal_quality,
        t.total_cost_milli,
        t.total_reward_milli,
    )
}

pub fn dataset_to_json(trajectories: &[Trajectory]) -> String {
    let items: Vec<String> = trajectories.iter().map(trajectory_to_json).collect();
    format!(
        r#"{{"version":{},"trajectories":[{}]}}"#,
        DATASET_VERSION,
        items.join(",")
    )
}

pub fn load_dataset(source: &str) -> Result<Vec<Trajectory>, String> {
    let json = parse_json_str(source).map_err(|e| e.to_string())?;
    let version = json
        .get("version")
        .and_then(Json::as_number)
        .and_then(|n| n.as_u64())
        .ok_or("dataset requires version")?;
    if version != DATASET_VERSION {
        return Err(format!("unsupported dataset version {version}"));
    }
    let items = json
        .get("trajectories")
        .and_then(Json::as_array)
        .ok_or("dataset requires trajectories")?;
    let mut out = Vec::new();
    for item in items {
        let get = |key: &str| {
            item.get(key)
                .ok_or_else(|| format!("trajectory missing {key}"))
        };
        let steps = get("steps")?
            .as_array()
            .ok_or("trajectory steps not an array")?;
        let mut records = Vec::new();
        for step in steps {
            let action_idx = step
                .get("action")
                .and_then(Json::as_number)
                .and_then(|n| n.as_u64())
                .ok_or("step missing action")? as usize;
            records.push(StepRecord {
                obs: obs_from_json(step.get("obs").ok_or("step missing obs")?)?,
                action: action_from_index(action_idx),
                cost_milli: step
                    .get("cost_milli")
                    .and_then(Json::as_number)
                    .and_then(|n| n.as_u64())
                    .ok_or("step missing cost_milli")?,
                reward_milli: step
                    .get("reward_milli")
                    .and_then(Json::as_number)
                    .and_then(|n| n.as_i64())
                    .ok_or("step missing reward_milli")?,
            });
        }
        out.push(Trajectory {
            policy: get("policy")?
                .as_str()
                .ok_or("trajectory policy not a string")?
                .to_string(),
            seed: get("seed")?
                .as_number()
                .and_then(|n| n.as_u64())
                .ok_or("trajectory missing seed")?,
            question_id: get("question_id")?
                .as_str()
                .ok_or("trajectory question_id not a string")?
                .to_string(),
            qtype: get("qtype")?
                .as_number()
                .and_then(|n| n.as_u64())
                .ok_or("trajectory missing qtype")? as u8,
            budget_milli: get("budget_milli")?
                .as_number()
                .and_then(|n| n.as_u64())
                .ok_or("trajectory missing budget_milli")?,
            steps: records,
            terminal_quality: get("terminal_quality")?
                .as_number()
                .and_then(|n| n.as_f64())
                .ok_or("trajectory missing terminal_quality")?,
            total_cost_milli: get("total_cost_milli")?
                .as_number()
                .and_then(|n| n.as_u64())
                .ok_or("trajectory missing total_cost_milli")?,
            total_reward_milli: get("total_reward_milli")?
                .as_number()
                .and_then(|n| n.as_i64())
                .ok_or("trajectory missing total_reward_milli")?,
        });
    }
    Ok(out)
}
