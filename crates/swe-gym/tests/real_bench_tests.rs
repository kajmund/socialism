//! Real-bench pins: the exported auto-renewal bench and its live JEV
//! fixture are frozen artifacts — a silent edit breaks CI, like the
//! synthetic bench before them.

use swe_gym::bench::load_bench;
use swe_gym::provider::{ReplayProvider, ResearchProvider};

const REAL_BENCH: &str = include_str!("../benchmarks/bench_real_v2.json");
const REAL_FIXTURE: &str = include_str!("../benchmarks/jev_fixture_real_v2.json");

#[test]
fn real_bench_is_frozen_and_complete() {
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    assert_eq!(bench.name, "swe-gym-real-auto-renewal");
    assert_eq!(bench.questions.len(), 1);
    let question = &bench.questions[0];
    assert_eq!(question.view.chunks.len(), 638);
    assert_eq!(question.evidence.len(), 20);
    assert_eq!(question.view.required_coverage, 20);
    assert!(
        question.scan_blind.is_empty(),
        "no blind set: real JEV answers"
    );
    // Real texts: every chunk carries actual contract text (headers and
    // table fragments can legitimately be short, so only non-empty is
    // pinned per chunk; the aggregate guards against an empty export).
    let total_text: usize = question
        .view
        .chunks
        .iter()
        .map(|chunk| {
            let text = question
                .texts
                .get(chunk)
                .unwrap_or_else(|| panic!("chunk {chunk} missing text"));
            assert!(!text.trim().is_empty(), "chunk {chunk} has empty text");
            text.len()
        })
        .sum();
    assert!(
        total_text > 100_000,
        "total text {total_text} looks like an empty export"
    );
    // The hard negative from the gold suite is in the bench and NOT evidence.
    assert!(
        question
            .view
            .chunks
            .iter()
            .any(|chunk| chunk.starts_with("Avtal_15_Bonusavtal:")),
        "the gold hard-negative document must be present"
    );
    assert!(
        question
            .evidence
            .iter()
            .all(|chunk| !chunk.starts_with("Avtal_15_Bonusavtal:")),
        "the hard negative must not be evidence"
    );
}

#[test]
fn real_fixture_is_frozen_and_matches_gold() {
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    let question = &bench.questions[0];
    let replay = ReplayProvider::load(REAL_FIXTURE).expect("real fixture must load");
    assert_eq!(replay.len(), 638);
    let evidence = &question.evidence;
    let mut gold_found = 0;
    let mut extra_fynd = 0;
    for chunk in &question.view.chunks {
        let answer = replay
            .analyze("scan", chunk, "")
            .unwrap_or_else(|error| panic!("fixture missing {chunk}: {error}"));
        assert!(answer.latency_ms > 0, "captured answers carry latency");
        if answer.choice == "fynd" {
            if evidence.contains(chunk) {
                gold_found += 1;
            } else {
                extra_fynd += 1;
            }
        }
    }
    // The live capture: JEV found every gold chunk and flagged two extra
    // candidates outside the gold. Pinned — this is measured model behavior
    // on the project's own corpus, and CI must notice if the fixture drifts.
    assert_eq!(gold_found, 20, "real JEV must find all gold evidence");
    assert_eq!(
        extra_fynd, 2,
        "real JEV flagged exactly two extra candidates"
    );
}

#[test]
fn real_bench_arms_solve_via_replay() {
    use swe_gym::benchmark::run_arm_with_provider;
    use swe_gym::strategy::{AdaptiveStrategy, OracleStrategy, SequentialStrategy};
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    let question = &bench.questions[0];
    let replay = ReplayProvider::load(REAL_FIXTURE).expect("real fixture must load");

    let mut a = SequentialStrategy;
    let a_report = run_arm_with_provider(
        &mut a,
        question,
        bench.total_budget_milli,
        &bench.tariffs,
        &replay,
    );
    assert!(a_report.solved);
    // Blind scanning needs 568 of 638 chunks to find all 20 evidence chunks.
    assert_eq!(a_report.calls.len(), 568);

    let mut oracle = OracleStrategy::new(question);
    let oracle_report = run_arm_with_provider(
        &mut oracle,
        question,
        bench.total_budget_milli,
        &bench.tariffs,
        &replay,
    );
    assert!(oracle_report.solved);
    // Perfect knowledge: exactly the 20 evidence chunks.
    assert_eq!(oracle_report.calls.len(), 20);

    let mut c = AdaptiveStrategy;
    let c_report = run_arm_with_provider(
        &mut c,
        question,
        bench.total_budget_milli,
        &bench.tariffs,
        &replay,
    );
    assert!(c_report.solved);
    assert_eq!(c_report.calls.len(), a_report.calls.len());
}
