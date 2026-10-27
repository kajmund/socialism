//! Research providers: the seam where real JEV/LLM services plug into the gym.
//!
//! A provider answers one chunk-analysis question; the harness meters every
//! call around it and never lets a provider touch the ledger. Live calls are
//! env-gated examples — benchmarks and tests replay fixtures or use the
//! synthetic corpus, so CI stays offline and deterministic.
//!
//! Failure policy: a provider error is loud (the run fails with a typed
//! error) and the reservation is released — nothing is charged for a call
//! that produced no answer. No retries, no silent fallbacks.

use std::cell::RefCell;
use std::collections::HashMap;
use std::time::Instant;

use swe_native::{parse_json_str, Json};

use crate::strategy::FakeCorpus;

#[derive(Clone, Debug, PartialEq)]
pub struct ProviderAnswer {
    /// Kernel-facing binary choice: "fynd" or "inget".
    pub choice: String,
    /// Provider confidence in basis points (0..10_000), facit-free metadata.
    pub score_bp: u32,
    /// Wall-clock latency in milliseconds (0 for offline providers).
    /// Measured separately from cost, as the strategy requires.
    pub latency_ms: u64,
    /// Raw provider payload, for provenance.
    pub raw: String,
}

pub trait ResearchProvider {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        chunk_text: &str,
    ) -> Result<ProviderAnswer, String>;
}

// ---------------------------------------------------------------------------
// Synthetic corpus provider (score model v1) — what the fake providers did
// before, now behind the same interface as the real ones.
// ---------------------------------------------------------------------------

impl ResearchProvider for FakeCorpus {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        _chunk_text: &str,
    ) -> Result<ProviderAnswer, String> {
        let (found, score) = match provider {
            "scan" => (self.scan(chunk_id), self.scan_score(chunk_id)),
            "deep" => (self.deep(chunk_id), self.deep_score(chunk_id)),
            other => return Err(format!("unknown provider {other:?} in corpus")),
        };
        Ok(ProviderAnswer {
            choice: if found { "fynd".into() } else { "inget".into() },
            score_bp: score,
            latency_ms: 0,
            raw: "corpus-score-model-v1".into(),
        })
    }
}

// ---------------------------------------------------------------------------
// Replay and record: deterministic fixtures for offline runs.
// ---------------------------------------------------------------------------

/// Deterministic provider over a captured fixture. Missing entries fail
/// loudly — a stale fixture must never silently fabricate an answer.
pub struct ReplayProvider {
    answers: HashMap<(String, String), ProviderAnswer>,
}

impl ReplayProvider {
    pub fn load(source: &str) -> Result<Self, String> {
        let json = parse_json_str(source).map_err(|error| error.to_string())?;
        let entries = json
            .get("entries")
            .and_then(Json::as_array)
            .ok_or("fixture requires entries")?;
        let mut answers = HashMap::new();
        for entry in entries {
            let provider = entry
                .get("provider")
                .and_then(Json::as_str)
                .ok_or("fixture entry requires provider")?
                .to_string();
            let chunk_id = entry
                .get("chunk_id")
                .and_then(Json::as_str)
                .ok_or("fixture entry requires chunk_id")?
                .to_string();
            let choice = entry
                .get("choice")
                .and_then(Json::as_str)
                .ok_or("fixture entry requires choice")?
                .to_string();
            let score_bp = entry
                .get("score_bp")
                .and_then(Json::as_number)
                .and_then(|number| number.as_u64())
                .ok_or("fixture entry requires score_bp")? as u32;
            let raw = entry
                .get("raw")
                .and_then(Json::as_str)
                .unwrap_or("")
                .to_string();
            let latency_ms = entry
                .get("latency_ms")
                .and_then(Json::as_number)
                .and_then(|number| number.as_u64())
                .unwrap_or(0);
            answers.insert(
                (provider, chunk_id),
                ProviderAnswer {
                    choice,
                    score_bp,
                    latency_ms,
                    raw,
                },
            );
        }
        if answers.is_empty() {
            return Err("fixture requires at least one entry".into());
        }
        Ok(Self { answers })
    }

    pub fn len(&self) -> usize {
        self.answers.len()
    }

    /// All captured answers, keyed by (provider, chunk_id).
    pub fn entries(&self) -> &HashMap<(String, String), ProviderAnswer> {
        &self.answers
    }

    pub fn is_empty(&self) -> bool {
        self.answers.is_empty()
    }
}

impl ResearchProvider for ReplayProvider {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        _chunk_text: &str,
    ) -> Result<ProviderAnswer, String> {
        self.answers
            .get(&(provider.to_string(), chunk_id.to_string()))
            .cloned()
            .ok_or_else(|| format!("replay fixture missing ({provider}, {chunk_id})"))
    }
}

/// Wraps a provider and captures every answer, for one-shot live capture runs
/// that become fixtures. Recording is an observer side-channel, so the
/// entries live behind a RefCell while the trait stays read-only.
pub struct RecordProvider<'a> {
    inner: &'a dyn ResearchProvider,
    entries: RefCell<Vec<(String, String, ProviderAnswer)>>,
}

impl<'a> RecordProvider<'a> {
    pub fn new(inner: &'a dyn ResearchProvider) -> Self {
        Self {
            inner,
            entries: RefCell::new(Vec::new()),
        }
    }

    /// Serialize the captured entries as a replay fixture.
    pub fn to_fixture(&self, source_label: &str) -> String {
        self.to_fixture_with(source_label, "")
    }

    /// Serialize with the question the captures answered, for provenance.
    pub fn to_fixture_with(&self, source_label: &str, question: &str) -> String {
        let entries: Vec<String> = self
            .entries
            .borrow()
            .iter()
            .map(|(provider, chunk_id, answer)| {
                format!(
                    r#"{{"provider":"{}","chunk_id":"{}","choice":"{}","score_bp":{},"latency_ms":{},"raw":"{}"}}"#,
                    json_escape(provider),
                    json_escape(chunk_id),
                    json_escape(&answer.choice),
                    answer.score_bp,
                    answer.latency_ms,
                    json_escape(&answer.raw),
                )
            })
            .collect();
        format!(
            r#"{{"source":"{}","question":"{}","entries":[{}]}}"#,
            json_escape(source_label),
            json_escape(question),
            entries.join(","),
        )
    }
}

impl ResearchProvider for RecordProvider<'_> {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        chunk_text: &str,
    ) -> Result<ProviderAnswer, String> {
        let answer = self.inner.analyze(provider, chunk_id, chunk_text)?;
        self.entries.borrow_mut().push((
            provider.to_string(),
            chunk_id.to_string(),
            answer.clone(),
        ));
        Ok(answer)
    }
}

// ---------------------------------------------------------------------------
// Live JEV (TypeSafe System One) over HTTP.
// ---------------------------------------------------------------------------

pub struct HttpJevProvider {
    api_key: String,
    base_url: String,
    model: String,
    instructions: String,
    criteria: (String, String, String),
    timeout_seconds: u64,
}

impl HttpJevProvider {
    pub fn new(api_key: &str, base_url: &str, model: &str) -> Self {
        Self {
            api_key: api_key.to_string(),
            base_url: base_url.trim_end_matches('/').to_string(),
            model: model.to_string(),
            instructions: "Innehåller texten evidens för frågan? Klassificera enbart fältet text."
                .to_string(),
            criteria: (
                "Texten innehåller evidens för frågan.".to_string(),
                "Texten innehåller inte evidens.".to_string(),
                "Texten räcker inte för att avgöra.".to_string(),
            ),
            timeout_seconds: 20,
        }
    }

    pub fn with_instructions(mut self, instructions: &str) -> Self {
        self.instructions = instructions.to_string();
        self
    }

    pub fn with_criteria(mut self, yes: &str, no: &str, uncertain: &str) -> Self {
        self.criteria = (yes.to_string(), no.to_string(), uncertain.to_string());
        self
    }
}

impl ResearchProvider for HttpJevProvider {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        chunk_text: &str,
    ) -> Result<ProviderAnswer, String> {
        let _ = (provider, chunk_id); // logged via the harness CallRecord
        let (criteria_yes, criteria_no, criteria_uncertain) = &self.criteria;
        let body = format!(
            r#"{{"model":"{}","state":{{"text":"{}"}},"questions":{{"evidence":{{"type":"choice","instructions":"{}","criteria":{{"YES":"{}","NO":"{}","UNCERTAIN":"{}"}}}}}}}}"#,
            json_escape(&self.model),
            json_escape(chunk_text),
            json_escape(&self.instructions),
            json_escape(criteria_yes),
            json_escape(criteria_no),
            json_escape(criteria_uncertain),
        );
        let url = format!("{}/v1/systemone", self.base_url);
        let started = Instant::now();
        let response = minreq::post(&url)
            .with_header("Authorization", &format!("Bearer {}", self.api_key))
            .with_header("Content-Type", "application/json")
            .with_body(body)
            .with_timeout(self.timeout_seconds)
            .send()
            .map_err(|error| format!("JEV transport failed: {error}"))?;
        let latency_ms = started.elapsed().as_millis() as u64;
        let text = response
            .as_str()
            .map_err(|error| format!("JEV response unreadable: {error}"))?
            .to_string();
        let json = parse_json_str(&text).map_err(|error| error.to_string())?;
        let row = json
            .get("answers")
            .and_then(|answers| answers.get("evidence"))
            .ok_or("JEV response missing answers.evidence")?;
        let (choice, score_bp) = map_jev_choice(row)?;
        Ok(ProviderAnswer {
            choice,
            score_bp,
            latency_ms,
            raw: text,
        })
    }
}

/// Extract the token usage from a raw JEV payload: (input_tokens,
/// output_tokens). None when the payload has no usage block.
pub fn usage_tokens(raw: &str) -> Option<(u64, u64)> {
    let json = parse_json_str(raw).ok()?;
    let usage = json.get("usage")?.as_object()?;
    // OpenAI-compatible providers use prompt_tokens/completion_tokens;
    // TypeSafe uses input_tokens/output_tokens. Read both spellings.
    let tokens = |names: &[&str]| -> u64 {
        for name in names {
            if let Some(value) = usage
                .get(*name)
                .and_then(Json::as_number)
                .and_then(|number| number.as_u64())
            {
                return value;
            }
        }
        0
    };
    Some((
        tokens(&["input_tokens", "prompt_tokens"]),
        tokens(&["output_tokens", "completion_tokens"]),
    ))
}

/// Live LLM over an OpenAI-compatible chat endpoint (Cerebras gpt-oss-120b
/// by default). Serves as the "deep" provider: same seam, real model.
pub struct HttpLlmProvider {
    api_key: String,
    base_url: String,
    model: String,
    system_prompt: String,
    reasoning_effort: String,
    timeout_seconds: u64,
}

impl HttpLlmProvider {
    pub fn new(api_key: &str, base_url: &str, model: &str) -> Self {
        Self {
            api_key: api_key.to_string(),
            base_url: base_url.trim_end_matches('/').to_string(),
            model: model.to_string(),
            system_prompt:
                "Klassificera avtalstexten. Svara med exakt ett ord: JA, NEJ eller OSÄKER."
                    .to_string(),
            reasoning_effort: "medium".to_string(),
            timeout_seconds: 60,
        }
    }

    pub fn with_system_prompt(mut self, prompt: &str) -> Self {
        self.system_prompt = prompt.to_string();
        self
    }
}

impl ResearchProvider for HttpLlmProvider {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        chunk_text: &str,
    ) -> Result<ProviderAnswer, String> {
        let _ = (provider, chunk_id); // logged via the harness CallRecord
                                      // gpt-oss-120b is a reasoning model: without reasoning_effort and a
                                      // real token budget it spends everything on hidden reasoning and never
                                      // emits `content` (observed live, finish_reason "length").
        let body = format!(
            r#"{{"model":"{}","messages":[{{"role":"system","content":"{}"}},{{"role":"user","content":"{}"}}],"max_tokens":1024,"temperature":0,"reasoning_effort":"{}"}}"#,
            json_escape(&self.model),
            json_escape(&self.system_prompt),
            json_escape(chunk_text),
            json_escape(&self.reasoning_effort),
        );
        let url = format!("{}/chat/completions", self.base_url);
        let started = Instant::now();
        let response = minreq::post(&url)
            .with_header("Authorization", &format!("Bearer {}", self.api_key))
            .with_header("Content-Type", "application/json")
            .with_body(body)
            .with_timeout(self.timeout_seconds)
            .send()
            .map_err(|error| format!("LLM transport failed: {error}"))?;
        let latency_ms = started.elapsed().as_millis() as u64;
        let text = response
            .as_str()
            .map_err(|error| format!("LLM response unreadable: {error}"))?
            .to_string();
        let json = parse_json_str(&text).map_err(|error| error.to_string())?;
        let content = json
            .get("choices")
            .and_then(Json::as_array)
            .and_then(|choices| choices.first())
            .and_then(|choice| choice.get("message"))
            .and_then(|message| message.get("content"))
            .and_then(Json::as_str)
            .ok_or("LLM response missing choices[0].message.content")?;
        let (choice, score_bp) = map_llm_word(content)?;
        Ok(ProviderAnswer {
            choice,
            score_bp,
            latency_ms,
            raw: text,
        })
    }
}

/// Map a one-word LLM answer to the gym convention. No confidence is
/// available, so the scores are fixed per word: JA 9500, NEJ 500,
/// OSÄKER 4500 (the suspicious band, same as JEV UNCERTAIN).
pub fn map_llm_word(content: &str) -> Result<(String, u32), String> {
    let first = content.trim().to_uppercase();
    let word = first.split_whitespace().next().unwrap_or("");
    match word {
        "JA" | "YES" => Ok(("fynd".into(), 9_500)),
        "NEJ" | "NO" => Ok(("inget".into(), 500)),
        "OSÄKER" | "OSAKER" | "UNCERTAIN" => Ok(("inget".into(), 4_500)),
        other => Err(format!(
            "invalid LLM answer {other:?} (content: {content:?})"
        )),
    }
}

/// Map one JEV choice row to the gym's (choice, score_bp) convention.
/// YES: 5000 + confidence*5000. NO: (1-confidence)*5000. UNCERTAIN: 4500 —
/// below the decision threshold, exactly the "suspicious" signal the adaptive
/// arm ranks first.
pub fn map_jev_choice(row: &Json) -> Result<(String, u32), String> {
    let choice = row
        .get("choice")
        .and_then(Json::as_str)
        .ok_or("JEV row missing choice")?
        .trim()
        .to_uppercase();
    let confidence = row
        .get("confidence")
        .and_then(Json::as_number)
        .and_then(|number| number.as_f64())
        .ok_or("JEV row missing confidence")?;
    if !(0.0..=1.0).contains(&confidence) {
        return Err(format!("JEV confidence out of range: {confidence}"));
    }
    match choice.as_str() {
        "YES" => Ok(("fynd".into(), (5000.0 + confidence * 5000.0).round() as u32)),
        "NO" => Ok(("inget".into(), ((1.0 - confidence) * 5000.0).round() as u32)),
        "UNCERTAIN" => Ok(("inget".into(), 4500)),
        other => Err(format!("invalid JEV choice {other:?}")),
    }
}

/// Resolve a secret for the live examples: process env first, then a
/// KEY=VALUE dotenv file as a local convenience. Values never leave the
/// process except over the provider's HTTPS call.
pub fn resolve_secret(name: &str, dotenv_path: &str) -> Option<String> {
    if let Ok(value) = std::env::var(name) {
        if !value.trim().is_empty() {
            return Some(value);
        }
    }
    let text = std::fs::read_to_string(dotenv_path).ok()?;
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((key, value)) = line.split_once('=') {
            if key.trim() == name {
                let value = value.trim().trim_matches('"').to_string();
                if !value.is_empty() {
                    return Some(value);
                }
            }
        }
    }
    None
}

/// Minimal JSON string escaping (the gym has no serde_json dependency).
pub fn json_escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 8);
    for c in value.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}
