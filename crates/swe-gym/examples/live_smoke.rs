//! Live JEV smoke: one real call through the HTTP provider.
//!
//! Usage: cargo run --example live_smoke
//!
//! Reads TYPESAFE_API_KEY / TYPESAFE_BASE_URL / JEV_MODEL from the process
//! env, falling back to backend/.env next to this repo. Fails loudly when the
//! key is missing. Costs one small JEV call.

use std::time::Instant;

use swe_gym::provider::{resolve_secret, HttpJevProvider, ResearchProvider};

fn main() {
    let api_key = resolve_secret("TYPESAFE_API_KEY", "../../backend/.env")
        .expect("TYPESAFE_API_KEY saknas (sätt i miljön eller backend/.env)");
    let base_url = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let provider = HttpJevProvider::new(&api_key, &base_url, &model);

    let started = Instant::now();
    let answer = provider
        .analyze(
            "scan",
            "smoke-1",
            "Styrelsen får förlänga avtalet automatiskt utan nytt godkännande från parterna.",
        )
        .expect("JEV must answer or fail loudly");
    let elapsed_ms = started.elapsed().as_millis();
    println!(
        "smoke: choice={} score_bp={} latency={} ms",
        answer.choice, answer.score_bp, elapsed_ms
    );
    let raw = answer.raw;
    let preview: String = raw.chars().take(300).collect();
    println!("raw: {preview}{}", if raw.len() > 300 { "…" } else { "" });
}
