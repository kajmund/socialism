//! Driver integration tests: the same workflow under a tight and a generous
//! budget, plus replay of the interrupted run's event log.

use swe_gym::driver::{build_chain_document, build_chunk_input, run_with_budget};
use swe_gym::ledger::Ledger;
use swe_native::RunStatus;

fn ground_truth(chunk: &str) -> Option<bool> {
    match chunk {
        "chunk-01" | "chunk-05" | "chunk-07" => Some(true),
        _ => Some(false),
    }
}

#[test]
fn tight_budget_cuts_the_chain_loudly() {
    let report = run_with_budget(
        &build_chain_document(10),
        "tight",
        &build_chunk_input(10),
        5_000,
        1_000,
        &ground_truth,
    )
    .unwrap();

    assert_eq!(report.calls.len(), 5);
    assert_eq!(report.denied, vec!["chunk-05"]);
    assert_eq!(report.status, RunStatus::Failed);
    let error = report.error.expect("budget exhaustion is a loud error");
    assert!(error.contains("budget exhausted"), "error was: {error}");
    assert_eq!(report.spent_milli, 5_000);
    assert_eq!(report.available_milli, 0);
}

#[test]
fn generous_budget_completes_and_keeps_the_rest() {
    let report = run_with_budget(
        &build_chain_document(10),
        "generous",
        &build_chunk_input(10),
        20_000,
        1_000,
        &ground_truth,
    )
    .unwrap();

    assert_eq!(report.calls.len(), 10);
    assert!(report.denied.is_empty());
    assert_eq!(report.status, RunStatus::Completed);
    assert!(report.error.is_none());
    let found = report
        .calls
        .iter()
        .filter(|call| call.choice == "fynd")
        .count();
    assert_eq!(found, 3);
    assert_eq!(report.spent_milli, 10_000);
    assert_eq!(report.available_milli, 10_000);
}

#[test]
fn interrupted_run_replays_identically() {
    let report = run_with_budget(
        &build_chain_document(10),
        "replay",
        &build_chunk_input(10),
        5_000,
        1_000,
        &ground_truth,
    )
    .unwrap();

    let replayed = Ledger::replay(report.ledger.events()).unwrap();
    assert_eq!(replayed.balances(), report.ledger.balances());
    assert_eq!(replayed.events(), report.ledger.events());
}
