//! A/B/C benchmark tests against the frozen benchmark file. Everything is
//! deterministic, so the tests pin the budget mechanics precisely — and pin
//! the frozen artifact itself, so a silent edit of the benchmark breaks CI.

use swe_gym::bench::{load_bench, BenchFile};
use swe_gym::benchmark::run_arm;
use swe_gym::ledger::{Amount, Ledger};
use swe_gym::strategy::{
    AdaptiveStrategy, OracleStrategy, ParallelEqualStrategy, Question, SequentialStrategy,
    Strategy, Tariffs,
};

const FROZEN: &str = include_str!("../benchmarks/bench_v1.json");

fn bench() -> BenchFile {
    load_bench(FROZEN).expect("frozen bench must load")
}

fn easy() -> Question {
    bench().question("Q1 lätt").unwrap().clone()
}

fn hard() -> Question {
    bench().question("Q2 svår").unwrap().clone()
}

// ---------------------------------------------------------------------------
// The frozen artifact itself is pinned.
// ---------------------------------------------------------------------------

#[test]
fn frozen_bench_is_pinned() {
    let bench = bench();
    assert_eq!(bench.version, 1);
    assert_eq!(bench.name, "swe-gym-minimal-bench");
    assert_eq!(bench.score_model, "v1");
    assert_eq!(bench.tariffs.scan_milli, 1_000);
    assert_eq!(bench.tariffs.deep_milli, 10_000);
    assert_eq!(bench.total_budget_milli, 30_000);
    assert_eq!(bench.questions.len(), 2);

    let easy = bench.question("Q1 lätt").unwrap();
    assert_eq!(easy.view.required_coverage, 2);
    assert!(easy.scan_blind.is_empty());

    let hard = bench.question("Q2 svår").unwrap();
    assert_eq!(hard.view.required_coverage, 3);
    assert!(hard.evidence.contains("chunk-07"));
    assert_eq!(hard.scan_blind.len(), 1);
    assert!(hard.scan_blind.contains("chunk-07"));
}

// ---------------------------------------------------------------------------
// Arm behavior, exact numbers.
// ---------------------------------------------------------------------------

#[test]
fn sequential_arm_solves_easy_with_early_stop() {
    let bench = bench();
    let report = run_arm(
        &mut SequentialStrategy,
        &easy(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert!(report.solved);
    assert!(!report.diagnostic);
    // Finds chunk-01 and chunk-05 by scan call 6 and stops: 6 coins spent.
    assert_eq!(report.spent_milli, 6_000);
    assert_eq!(report.leftover_milli, 24_000);
    assert_eq!(report.calls.len(), 6);
    assert!(report.denied.is_empty());
    assert!(report.calls.iter().all(|call| call.provider == "scan"));
    assert_eq!(report.found, vec!["chunk-01", "chunk-05"]);
}

#[test]
fn parallel_arm_pays_for_speculation_on_easy() {
    let bench = bench();
    let report = run_arm(
        &mut ParallelEqualStrategy,
        &easy(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert!(report.solved);
    // Scan solves it, but the deep branch burned one call before being
    // stopped by its own half-budget: 6 scan + 10 deep = 16 coins.
    assert_eq!(report.spent_milli, 16_000);
    assert_eq!(report.leftover_milli, 14_000);
    let scan_calls = report
        .calls
        .iter()
        .filter(|call| call.provider == "scan")
        .count();
    let deep_calls = report
        .calls
        .iter()
        .filter(|call| call.provider == "deep")
        .count();
    assert_eq!((scan_calls, deep_calls), (6, 1));
    assert_eq!(report.denied.len(), 1);
    assert_eq!(report.denied[0].0, "b-deep");
}

#[test]
fn hard_question_unsolved_by_both_blind_arms() {
    let bench = bench();
    let a = run_arm(
        &mut SequentialStrategy,
        &hard(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    let b = run_arm(
        &mut ParallelEqualStrategy,
        &hard(),
        bench.total_budget_milli,
        &bench.tariffs,
    );

    assert!(!a.solved && !b.solved);
    // A: scan all (10) then deep escalation burns the rest (20) and gets
    // denied on the third deep call.
    assert_eq!(a.spent_milli, 30_000);
    assert_eq!(a.leftover_milli, 0);
    assert_eq!(a.denied.len(), 1);
    // B: deep branch dies on its second call (5 < 10), leftover flows to the
    // scan branch; both finish without reaching chunk-07.
    assert_eq!(b.spent_milli, 20_000);
    assert_eq!(b.leftover_milli, 10_000);
    assert_eq!(b.denied.len(), 1);
    assert_eq!(a.found, vec!["chunk-01", "chunk-05"]);
    assert_eq!(b.found, vec!["chunk-01", "chunk-05"]);
}

#[test]
fn adaptive_arm_solves_hard_within_budget() {
    let bench = bench();
    let report = run_arm(
        &mut AdaptiveStrategy,
        &hard(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert!(report.solved);
    // Scan all (10) + exactly one deep call on the suspicious chunk: the
    // revision rule ranked chunk-07 (score 4500) above the clear negatives
    // (1000). 10 + 10 = 20 spent.
    assert_eq!(report.spent_milli, 20_000);
    assert_eq!(report.leftover_milli, 10_000);
    assert!(report.denied.is_empty());
    let deep_calls: Vec<&swe_gym::driver::CallRecord> = report
        .calls
        .iter()
        .filter(|call| call.provider == "deep")
        .collect();
    assert_eq!(deep_calls.len(), 1);
    assert_eq!(deep_calls[0].chunk, "chunk-07");
    assert_eq!(report.found, vec!["chunk-01", "chunk-05", "chunk-07"]);
}

#[test]
fn adaptive_arm_ties_sequential_on_easy() {
    // On the easy question there is nothing to adapt to: C stops at the same
    // early-stop point as A, without any speculative deep calls.
    let bench = bench();
    let a = run_arm(
        &mut SequentialStrategy,
        &easy(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    let c = run_arm(
        &mut AdaptiveStrategy,
        &easy(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert!(c.solved);
    assert_eq!(c.spent_milli, a.spent_milli);
    assert_eq!(c.calls.len(), a.calls.len());
    assert!(c.calls.iter().all(|call| call.provider == "scan"));
    assert_eq!(c.found, a.found);
}

// ---------------------------------------------------------------------------
// The oracle arm: the cost floor. Diagnostic only, never a contender.
// ---------------------------------------------------------------------------

#[test]
fn oracle_arm_defines_the_cost_floor_on_hard() {
    let bench = bench();
    let hard = hard();
    let mut oracle = OracleStrategy::new(&hard);
    let report = run_arm(&mut oracle, &hard, bench.total_budget_milli, &bench.tariffs);

    assert!(report.diagnostic);
    assert!(report.solved);
    // Perfect knowledge: scan the two visible evidence chunks, deep the one
    // hidden chunk. 2 + 10 = 12 coins — vs C's 20.
    assert_eq!(report.spent_milli, 12_000);
    assert_eq!(report.calls.len(), 3);
    assert!(report.denied.is_empty());
    assert_eq!(report.found, vec!["chunk-01", "chunk-05", "chunk-07"]);
}

#[test]
fn oracle_floor_on_easy_is_two_scans() {
    let bench = bench();
    let easy = easy();
    let mut oracle = OracleStrategy::new(&easy);
    let report = run_arm(&mut oracle, &easy, bench.total_budget_milli, &bench.tariffs);

    assert!(report.diagnostic);
    assert!(report.solved);
    assert_eq!(report.spent_milli, 2_000);
    assert_eq!(report.calls.len(), 2);
}

// ---------------------------------------------------------------------------
// Ledger integrity across all arms, including the oracle.
// ---------------------------------------------------------------------------

fn assert_replays(
    strategy: &mut dyn Strategy,
    question: &Question,
    budget: Amount,
    tariffs: &Tariffs,
) {
    let report = run_arm(strategy, question, budget, tariffs);
    let replayed = Ledger::replay(report.ledger.events()).unwrap();
    assert_eq!(replayed.balances(), report.ledger.balances());
    assert_eq!(replayed.events(), report.ledger.events());
}

#[test]
fn arm_event_logs_replay_identically() {
    let bench = bench();
    let easy = easy();
    let hard = hard();
    let mut oracle_easy = OracleStrategy::new(&easy);
    let mut oracle_hard = OracleStrategy::new(&hard);

    assert_replays(
        &mut SequentialStrategy,
        &easy,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut ParallelEqualStrategy,
        &easy,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut AdaptiveStrategy,
        &easy,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut oracle_easy,
        &easy,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut SequentialStrategy,
        &hard,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut ParallelEqualStrategy,
        &hard,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut AdaptiveStrategy,
        &hard,
        bench.total_budget_milli,
        &bench.tariffs,
    );
    assert_replays(
        &mut oracle_hard,
        &hard,
        bench.total_budget_milli,
        &bench.tariffs,
    );
}

#[test]
fn hard_cap_holds_across_all_branch_accounts() {
    let bench = bench();
    let report = run_arm(
        &mut ParallelEqualStrategy,
        &hard(),
        bench.total_budget_milli,
        &bench.tariffs,
    );
    // No account may ever have spent more than its transfers in; total spent
    // plus leftover equals the run cap exactly.
    let total_spent: u64 = report
        .ledger
        .balances()
        .values()
        .map(|balance| balance.spent)
        .sum();
    assert_eq!(total_spent, report.spent_milli);
    assert_eq!(
        report.spent_milli + report.leftover_milli,
        bench.total_budget_milli
    );
}
