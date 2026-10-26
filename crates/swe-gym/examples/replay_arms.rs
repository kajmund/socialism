//! Offline arms run on real JEV answers: the captured fixture drives the
//! same machinery, deterministically, with no live calls.
//!
//! The question is the suite's auto-renewal classification; the facit labels
//! the two chunks JEV answered YES. Everything else — arms, ledger, budget —
//! is the standard harness.
//!
//! Usage: cargo run --example replay_arms

use std::collections::HashSet;

use swe_gym::benchmark::run_arm_with_provider;
use swe_gym::provider::ReplayProvider;
use swe_gym::strategy::{
    AdaptiveStrategy, OracleStrategy, Question, QuestionView, SequentialStrategy, Tariffs,
};

const BUDGET: u64 = 30_000;
const TARIFFS: Tariffs = Tariffs {
    scan_milli: 1_000,
    deep_milli: 10_000,
};

fn main() {
    let source = std::fs::read_to_string("benchmarks/jev_fixture_v1.json")
        .expect("fixture must be present — run capture_fixture first");
    let replay = ReplayProvider::load(&source).expect("fixture must load");

    let chunks: Vec<String> = [
        "chunk-r1", "chunk-r2", "chunk-r3", "chunk-r4", "chunk-r5", "chunk-r6",
    ]
    .iter()
    .map(|chunk| chunk.to_string())
    .collect();
    // Facit = the chunks JEV answered YES in the capture (r1, r3).
    let question = Question {
        view: QuestionView {
            id: "Q3 riktig (JEV-replay)".into(),
            chunks,
            required_coverage: 2,
            question: String::new(),
        },
        evidence: HashSet::from(["chunk-r1".into(), "chunk-r3".into()]),
        scan_blind: HashSet::new(),
        noise_seed: 0,
        budget_milli: 0,
        texts: std::collections::HashMap::new(),
    };

    println!("=== Armar på riktiga JEV-svar (replay-fixtur, offline) ===\n");
    let mut a = SequentialStrategy;
    let a_report = run_arm_with_provider(&mut a, &question, BUDGET, &TARIFFS, &replay);
    let mut c = AdaptiveStrategy;
    let c_report = run_arm_with_provider(&mut c, &question, BUDGET, &TARIFFS, &replay);
    let mut oracle = OracleStrategy::new(&question);
    let cx_report = run_arm_with_provider(&mut oracle, &question, BUDGET, &TARIFFS, &replay);
    for report in [&a_report, &c_report, &cx_report] {
        let solved = if report.solved { "LÖST " } else { "OLÖST" };
        let scan_calls = report
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
        let label = if report.diagnostic {
            format!("{} [tak]", report.strategy)
        } else {
            report.strategy.to_string()
        };
        println!(
            "  {:<28} {}  spend {}  scan-anrop {}  fynd: [{}]",
            label,
            solved,
            format_amount(report.spent_milli),
            scan_calls,
            report.found.join(", "),
        );
    }
}

fn format_amount(milli: u64) -> String {
    format!("{}.{:03}", milli / 1_000, milli % 1_000)
}
