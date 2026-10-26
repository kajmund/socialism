//! Live capture of real JEV answers for the real auto-renewal bench.
//!
//! Reads benchmarks/bench_real_v2.json, asks JEV the gold classify question
//! for every chunk (concurrently, 8 threads — the suite's own research
//! concurrency), and freezes the answers into
//! benchmarks/jev_fixture_real_v2.json. One-shot; everything downstream is
//! offline replay.
//!
//! Usage: cargo run --example capture_real   (costs 638 small JEV calls)

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpJevProvider, RecordProvider, ResearchProvider};

const INSTRUCTIONS: &str = "Innehåller texten en bestämmelse där avtalet förlängs automatiskt utan ett nytt uttryckligt godkännande från båda parterna? Classify only the candidate `text` field. YES only if the candidate text itself contains the provision asked about. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN. Do not drop UNCERTAIN; it is a valid outcome.";

fn main() {
    let bench = load_bench_file("benchmarks/bench_real_v2.json").expect("real bench must exist");
    let question = &bench.questions[0];
    let chunks: Vec<(String, String)> = question
        .view
        .chunks
        .iter()
        .map(|chunk| {
            (
                chunk.clone(),
                question.texts.get(chunk).cloned().unwrap_or_default(),
            )
        })
        .collect();
    let total = chunks.len();
    println!("fångar JEV-svar för {total} chunks…");

    let api_key =
        resolve_secret("TYPESAFE_API_KEY", "../../backend/.env").expect("TYPESAFE_API_KEY saknas");
    let base_url = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    // Thread-safe recording: the recorder's RefCell is not Sync, so each
    // worker owns its own recorder and the entries are merged after joining.
    let done = Arc::new(AtomicUsize::new(0));
    let mut handles = Vec::new();
    for worker in 0..8 {
        let chunks: Vec<(String, String)> = chunks
            .iter()
            .enumerate()
            .filter(|(index, _)| index % 8 == worker)
            .map(|(_, pair)| pair.clone())
            .collect();
        let live = HttpJevProvider::new(&api_key, &base_url, &model)
            .with_instructions(INSTRUCTIONS)
            .with_criteria(
                "The candidate text itself contains the provision asked about.",
                "The candidate text does not contain that provision.",
                "The supplied text and context are not enough to decide.",
            );
        let done = Arc::clone(&done);
        handles.push(std::thread::spawn(
            move || -> Vec<(String, String, swe_gym::provider::ProviderAnswer)> {
                let recorder = RecordProvider::new(&live);
                let mut entries = Vec::new();
                for (chunk_id, text) in &chunks {
                    let answer = recorder
                        .analyze("scan", chunk_id, text)
                        .expect("JEV must answer or fail loudly");
                    entries.push((chunk_id.clone(), "scan".to_string(), answer));
                    let n = done.fetch_add(1, Ordering::SeqCst) + 1;
                    if n % 100 == 0 {
                        println!("  {n}/{total} fångade");
                    }
                }
                entries
            },
        ));
    }
    let mut entries: Vec<(String, String, swe_gym::provider::ProviderAnswer)> = Vec::new();
    for handle in handles {
        entries.extend(handle.join().unwrap());
    }
    entries.sort_by(|a, b| a.0.cmp(&b.0));

    // Serialize in the gym fixture format (like RecordProvider::to_fixture).
    let mut json_entries = String::new();
    for (chunk_id, provider, answer) in &entries {
        json_entries.push_str(&format!(
            r#"{{"provider":"{}","chunk_id":"{}","choice":"{}","score_bp":{},"latency_ms":{},"raw":"{}"}},"#,
            provider,
            chunk_id,
            answer.choice,
            answer.score_bp,
            answer.latency_ms,
            swe_gym::provider::json_escape(&answer.raw),
        ));
    }
    json_entries.pop(); // trailing comma
    let fixture = format!(
        r#"{{"source":"live JEV capture real-bench epoch-{}","question":"{}","entries":[{}]}}"#,
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0),
        swe_gym::provider::json_escape("auto-renewal classify question"),
        json_entries,
    );
    std::fs::write("benchmarks/jev_fixture_real_v2.json", fixture)
        .expect("fixture must be writable");
    println!(
        "skrev benchmarks/jev_fixture_real_v2.json ({} anrop)",
        entries.len()
    );
}
