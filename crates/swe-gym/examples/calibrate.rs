//! Tariff calibration from the captured fixture — fully offline.
//!
//! Usage: cargo run --example calibrate
//!
//! Reads benchmarks/jev_fixture_v1.json, extracts measured token usage and
//! latency per call for both providers, and derives proposed tariffs under a
//! stated anchor, next to what the frozen experimental prices imply. The
//! deep = 10x ratio was previously uncalibrated; the LLM capture closes it.

use swe_gym::calibrate::{calibrate, CallSample};
use swe_gym::provider::{usage_tokens, ReplayProvider, ResearchProvider};

fn main() {
    let source = std::fs::read_to_string("benchmarks/jev_fixture_v1.json")
        .expect("fixture must be present — run capture_fixture first");
    let replay = ReplayProvider::load(&source).expect("fixture must load");
    let chunks = [
        "chunk-r1", "chunk-r2", "chunk-r3", "chunk-r4", "chunk-r5", "chunk-r6",
    ];

    // Stated anchor: one Sweycoin buys 1000 tokens or one second of
    // wall-clock, whichever a call consumes more of.
    println!("=== Tariffkalibrering från fryst fixtur ===");
    for (provider, frozen_price, label) in [
        ("scan", 1_000, "scan (JEV)"),
        ("deep", 10_000, "deep (LLM)"),
    ] {
        let mut samples = Vec::new();
        for chunk in chunks {
            let answer = replay
                .analyze(provider, chunk, "")
                .expect("fixture entries must cover the chunks");
            let (input, output) = usage_tokens(&answer.raw).unwrap_or((0, 0));
            samples.push(CallSample {
                tokens: input + output,
                latency_ms: answer.latency_ms,
            });
        }
        let report = calibrate(&samples, 1_000, 1_000, frozen_price);
        println!(
            "{label:<12} samples {}   medeltokens {:.0}   medianlatens {} ms",
            report.samples, report.mean_tokens, report.median_latency_ms,
        );
        println!(
            "  fryst {:<12} {} Sweycoin → innebär {:.6} coin/token, {:.3} coin/s",
            provider,
            milli_to_coins(report.current_tariff_milli),
            report.implied_coins_per_token,
            report.implied_coins_per_second,
        );
        println!(
            "  kalibrerat {:<8} {} Sweycoin (ankare: 1 coin = 1000 tokens eller 1 s)",
            provider,
            milli_to_coins(report.proposed_tariff_milli),
        );
    }
    println!();
    println!("(deep-kvoten 10x var tidigare okalibrerad — nu mätt mot riktig LLM)");
}

fn milli_to_coins(milli: u64) -> String {
    format!("{}.{:03}", milli / 1_000, milli % 1_000)
}
