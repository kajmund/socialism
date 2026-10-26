//! Frozen benchmark files: questions, tariffs and budget in one versioned
//! artifact. Strategies never load this file — the harness does, and hands
//! strategies only the facit-free `QuestionView`.
//!
//! The facit lives here on purpose: it is benchmark data, like golden answers
//! in any eval set, and must be kept out of strategy code (enforced by the
//! type system).

use std::collections::{HashMap, HashSet};

use swe_native::{parse_json_str, Json};

use crate::ledger::Amount;
use crate::strategy::{Question, QuestionView, Tariffs};

#[derive(Clone, Debug)]
pub struct BenchFile {
    pub version: u64,
    pub name: String,
    pub score_model: String,
    pub tariffs: Tariffs,
    pub total_budget_milli: Amount,
    pub questions: Vec<Question>,
}

impl BenchFile {
    pub fn question(&self, id: &str) -> Option<&Question> {
        self.questions
            .iter()
            .find(|question| question.view.id == id)
    }
}

/// Parse a bench document. Fails loudly on any missing or malformed field —
/// no silent defaults.
pub fn load_bench(source: &str) -> Result<BenchFile, String> {
    let json = parse_json_str(source).map_err(|error| error.to_string())?;
    let version = json
        .get("version")
        .and_then(Json::as_number)
        .and_then(|number| number.as_u64())
        .ok_or("bench requires a version")?;
    if version != 1 {
        return Err(format!("unsupported bench version {version}"));
    }
    let name = required_str(&json, "name")?.to_string();
    let score_model = required_str(&json, "score_model")?.to_string();
    let total_budget_milli = required_u64(&json, "total_budget_milli")?;

    let tariffs = json
        .get("tariffs_milli")
        .and_then(Json::as_object)
        .ok_or("bench requires tariffs_milli")?;
    let scan_milli = tariffs
        .get("scan")
        .and_then(Json::as_number)
        .and_then(|number| number.as_u64())
        .ok_or("tariffs_milli requires scan")?;
    let deep_milli = tariffs
        .get("deep")
        .and_then(Json::as_number)
        .and_then(|number| number.as_u64())
        .ok_or("tariffs_milli requires deep")?;

    let questions_json = json
        .get("questions")
        .and_then(Json::as_array)
        .ok_or("bench requires questions")?;
    let mut questions = Vec::with_capacity(questions_json.len());
    for question in questions_json {
        let id = required_str(question, "id")?.to_string();
        let required_coverage = required_u64(question, "required_coverage")? as usize;
        let question_text = question
            .get("question")
            .and_then(Json::as_str)
            .unwrap_or("")
            .to_string();
        let chunks = string_array(question, "chunks")?;
        let evidence: HashSet<String> = string_array(question, "evidence")?.into_iter().collect();
        let scan_blind: HashSet<String> =
            string_array(question, "scan_blind")?.into_iter().collect();
        let texts: HashMap<String, String> = question
            .get("texts")
            .and_then(Json::as_object)
            .map(|object| {
                object
                    .iter()
                    .map(|(chunk, text)| (chunk.clone(), text.as_str().unwrap_or("").to_string()))
                    .collect()
            })
            .unwrap_or_default();
        if evidence.is_empty() {
            return Err(format!(
                "question {id:?} requires at least one evidence chunk"
            ));
        }
        questions.push(Question {
            view: QuestionView {
                id,
                chunks,
                required_coverage,
                question: question_text,
            },
            evidence,
            scan_blind,
            noise_seed: 0,
            budget_milli: 0,
            texts,
        });
    }
    if questions.is_empty() {
        return Err("bench requires at least one question".into());
    }

    Ok(BenchFile {
        version,
        name,
        score_model,
        tariffs: Tariffs {
            scan_milli,
            deep_milli,
        },
        total_budget_milli,
        questions,
    })
}

/// Load a bench document from disk.
pub fn load_bench_file(path: &str) -> Result<BenchFile, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read bench file {path:?}: {error}"))?;
    load_bench(&text)
}

fn required_str<'a>(json: &'a Json, field: &str) -> Result<&'a str, String> {
    json.get(field)
        .and_then(Json::as_str)
        .ok_or_else(|| format!("bench requires {field}"))
}

fn required_u64(json: &Json, field: &str) -> Result<u64, String> {
    json.get(field)
        .and_then(Json::as_number)
        .and_then(|number| number.as_u64())
        .ok_or_else(|| format!("bench requires {field}"))
}

fn string_array(json: &Json, field: &str) -> Result<Vec<String>, String> {
    json.get(field)
        .and_then(Json::as_array)
        .ok_or_else(|| format!("{field} must be an array"))?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_string)
                .ok_or_else(|| format!("{field} items must be strings"))
        })
        .collect()
}
