//! Live capture of the missing third capability: LLM deep answers for
//! the frozen real bench (docs/SWE_Sweycoins_v2.md 18). Captures once,
//! then frozen as benchmarks/real_fixtures_deep/{qid}.json — the deep
//! fixture that unblocks the three-capability benchmark.
//!
//! Candidates per question: the top 25 similarity-ranked chunks plus the
//! evidence chunks in JEV's blind spot (so the fixture is informative
//! where the scan capability provably fails). Facit guides WHICH chunks
//! to capture, never the answers themselves.
//!
//! Env-gated, live, bounded cost (~130 LLM calls). Run with:
//!   cargo run --example v2_capture_deep

use std::collections::HashSet;

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpLlmProvider, RecordProvider, ResearchProvider};

fn main() {
    let llm_key = resolve_secret("CEREBRAS_API_KEY", "../../backend/.env")
        .expect("CEREBRAS_API_KEY saknas (sätt i miljön eller backend/.env)");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());

    let bench = load_bench_file("benchmarks/bench_real_v2.json").expect("real bench must load");
    std::fs::create_dir_all("benchmarks/real_fixtures_deep").expect("create fixture dir");

    for question in &bench.questions {
        let system = format!(
            "Du klassificerar avtalstext. Fråga: {} Svara med exakt ett ord: JA, NEJ eller OSÄKER.",
            question.view.question
        );
        let deep =
            HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(&system);
        let recorder = RecordProvider::new(&deep);

        let mut candidates: Vec<String> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for chunk in question.view.scan_order.iter().take(25) {
            if seen.insert(chunk.clone()) {
                candidates.push(chunk.clone());
            }
        }
        for chunk in &question.evidence {
            if question.scan_blind.contains(chunk) && seen.insert(chunk.clone()) {
                candidates.push(chunk.clone());
            }
        }

        for chunk in &candidates {
            let text = question.texts.get(chunk).cloned().unwrap_or_default();
            recorder
                .analyze("deep", chunk, &text)
                .unwrap_or_else(|e| panic!("LLM must answer {chunk} or fail loudly: {e}"));
        }

        let fixture = recorder.to_fixture_with("swe-gym-v2-deep-capture", &question.view.question);
        let path = format!("benchmarks/real_fixtures_deep/{}.json", question.view.id);
        std::fs::write(&path, fixture).expect("write deep fixture");
        println!(
            "{}: {} deep answers -> {}",
            question.view.id,
            candidates.len(),
            path
        );
    }
}
