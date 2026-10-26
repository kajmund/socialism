//! Sweycoin PoC demo, two sections:
//!
//! 1. Budget cut: the same small workflow under two budgets — the meter in
//!    action, denial is loud.
//! 2. Arms: strategy A (sequential) vs B (parallel, equal start budget) on the
//!    same questions with the same hard cap.
//!
//! No external services — providers are pure functions and every coin is
//! visible in the console output and the event log.
//!
//! Run with: cargo run --quiet

use std::collections::HashMap;

use swe_gym::bandit::{
    train_bandit, train_sequential, BanditPolicy, BanditStrategy, ScanPolicy,
    SequentialBanditStrategy,
};
use swe_gym::bench::load_bench_file;
use swe_gym::benchmark::{run_arm, run_arm_with_provider, ArmReport};
use swe_gym::driver::{build_chain_document, build_chunk_input, run_with_budget, RunReport};
use swe_gym::gen::QuestionGenerator;
use swe_gym::ledger::{EventKind, Ledger};
use swe_gym::provider::ReplayProvider;
use swe_gym::strategy::{
    AdaptiveStrategy, OracleStrategy, ParallelEqualStrategy, Question, SequentialStrategy, Strategy,
};
use swe_gym::td::{train_td, TdPolicy, TdSequentialStrategy};

const CHUNK_COUNT: usize = 10;
const TARIFF_MILLI: u64 = 1_000; // 1 Sweycoin per analyze call

fn main() {
    demo_budget_cut();
    demo_arms();
    demo_bandit();
    demo_noise();
    demo_sequential();
    demo_td();
    demo_td_structured();
    demo_real_bench();
}

// ---------------------------------------------------------------------------
// Section 1: the meter cuts a run when the budget runs out.
// ---------------------------------------------------------------------------

fn demo_budget_cut() {
    let document = build_chain_document(CHUNK_COUNT);
    let input = build_chunk_input(CHUNK_COUNT);

    println!("Sweycoin PoC — samma workflow, två budgetar (tariff: 1 Sweycoin per anrop)\n");

    let budget_5 = run_with_budget(
        &document,
        "demo-budget-5",
        &input,
        5_000,
        TARIFF_MILLI,
        &ground_truth,
    )
    .expect("budget 5 run must drive to a terminal state");
    print_report("budget 5", &budget_5);

    let budget_20 = run_with_budget(
        &document,
        "demo-budget-20",
        &input,
        20_000,
        TARIFF_MILLI,
        &ground_truth,
    )
    .expect("budget 20 run must drive to a terminal state");
    print_report("budget 20", &budget_20);

    println!("--- ledger replay check ---");
    for (label, report) in [("budget 5", &budget_5), ("budget 20", &budget_20)] {
        let replayed = Ledger::replay(report.ledger.events()).expect("event log must replay");
        let equal = report.ledger.balances() == replayed.balances();
        println!("{label}: replay == live: {equal}");
    }
    println!();
}

// ---------------------------------------------------------------------------
// Section 2: arms on the frozen benchmark, same hard cap. The oracle arm is
// diagnostic: it bounds the ceiling, it never counts as a contender.
// ---------------------------------------------------------------------------

fn demo_arms() {
    let bench = load_bench_file("benchmarks/bench_v1.json").expect("frozen bench must be present");
    let tariffs = bench.tariffs;
    let total_budget = bench.total_budget_milli;

    println!(
        "=== Bench {} (v{}, score-model {}) — budget {}, tariff: scan {} / deep {} ===\n",
        bench.name,
        bench.version,
        bench.score_model,
        format_amount(total_budget),
        format_amount(tariffs.scan_milli),
        format_amount(tariffs.deep_milli),
    );
    for question in &bench.questions {
        println!(
            "{} — krav {}/3, {}",
            question.view.id,
            question.view.required_coverage,
            question_label(question),
        );
        let a = run_arm(&mut SequentialStrategy, question, total_budget, &tariffs);
        let b = run_arm(&mut ParallelEqualStrategy, question, total_budget, &tariffs);
        let c = run_arm(&mut AdaptiveStrategy, question, total_budget, &tariffs);
        let mut oracle = OracleStrategy::new(question);
        let cx = run_arm(&mut oracle, question, total_budget, &tariffs);
        print_arm_report(&a);
        print_arm_report(&b);
        print_arm_report(&c);
        print_arm_report(&cx);
        println!();
    }

    println!("--- ledger replay check (armar) ---");
    for question in &bench.questions {
        let mut oracle = OracleStrategy::new(question);
        let reports = [
            run_arm(&mut SequentialStrategy, question, total_budget, &tariffs),
            run_arm(&mut ParallelEqualStrategy, question, total_budget, &tariffs),
            run_arm(&mut AdaptiveStrategy, question, total_budget, &tariffs),
            run_arm(&mut oracle, question, total_budget, &tariffs),
        ];
        for report in &reports {
            let replayed = Ledger::replay(report.ledger.events()).expect("event log must replay");
            let equal = report.ledger.balances() == replayed.balances();
            println!(
                "{} / {}: replay == live: {equal}",
                question.view.id, report.strategy,
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Section 3: the first learned policy — a contextual bandit over one budget
// decision. Training is online on synthetic questions; evaluation is on the
// frozen bench (held-out) and fresh generated questions. Scripted providers,
// reported as such.
// ---------------------------------------------------------------------------

fn demo_bandit() {
    let bench = load_bench_file("benchmarks/bench_v1.json").expect("frozen bench must be present");
    let tariffs = bench.tariffs;
    let total_budget = bench.total_budget_milli;

    println!();
    println!("=== D: kontextuell bandit (linjär SGD, ε=0.2, lr=0.1) ===");
    println!(
        "(syntetisk korpus, scriptade providers — mäter policyinlärning, inte modellkvalitet)"
    );

    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate(300);
    let mut policy = BanditPolicy::new(42, 0.2, 0.1);
    let records = train_bandit(&mut policy, &train_questions, total_budget, &tariffs);
    println!(
        "träning: {} beslut, {} uppdateringar   reward-medel: första 50 = {:.2}, sista 50 = {:.2}",
        records.len(),
        policy.updates(),
        mean_reward(&records[..50]),
        mean_reward(&records[250..]),
    );

    policy.set_epsilon(0.0); // fryser utforskningen

    println!("\nfryst policy (ε=0) på held-out-benchen:");
    for question in &bench.questions {
        let mut bandit = BanditStrategy::new(policy.clone());
        let report = run_arm(&mut bandit, question, total_budget, &tariffs);
        print_arm_report(&report);
    }

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate(100);
    let (a_solved, a_spend) = eval_aggregate(&eval_questions, total_budget, &tariffs, || {
        Box::new(SequentialStrategy)
    });
    let (c_solved, c_spend) = eval_aggregate(&eval_questions, total_budget, &tariffs, || {
        Box::new(AdaptiveStrategy)
    });
    let eval_policy = policy.clone();
    let (d_solved, d_spend) = eval_aggregate(&eval_questions, total_budget, &tariffs, move || {
        Box::new(BanditStrategy::new(eval_policy.clone()))
    });
    println!("\n100 nya genererade frågor (held-out):");
    println!(
        "  A sekventiell: {a_solved}/100 lösta, total spend {}",
        format_amount(a_spend)
    );
    println!(
        "  C adaptiv:     {c_solved}/100 lösta, total spend {}",
        format_amount(c_spend)
    );
    println!(
        "  D bandit:      {d_solved}/100 lösta, total spend {}",
        format_amount(d_spend)
    );
}

fn mean_reward(records: &[swe_gym::bandit::TrainingRecord]) -> f64 {
    if records.is_empty() {
        return 0.0;
    }
    records.iter().map(|record| record.reward).sum::<f64>() / records.len() as f64
}

fn eval_aggregate(
    questions: &[Question],
    total_budget: u64,
    tariffs: &swe_gym::strategy::Tariffs,
    make: impl FnMut() -> Box<dyn Strategy>,
) -> (usize, u64) {
    let mut solved = 0;
    let mut spend = 0;
    let mut make = make;
    for question in questions {
        let mut strategy = make();
        let report = run_arm(strategy.as_mut(), question, total_budget, tariffs);
        if report.solved {
            solved += 1;
        }
        spend += report.spent_milli;
    }
    (solved, spend)
}

// ---------------------------------------------------------------------------
// Section 4: generalization stress test — noisy score model v2, varied
// budgets. Trains the bandit on 2000 noisy questions and compares it with the
// hand-coded arms on 500 fresh ones. Scripted data, reported as such.
// ---------------------------------------------------------------------------

fn demo_noise() {
    let tariffs = swe_gym::strategy::Tariffs {
        scan_milli: 1_000,
        deep_milli: 10_000,
    };

    println!();
    println!("=== E: generalisering — brusig score-modell v2, varierade budgetar ===");
    println!(
        "(syntetisk korpus, scriptade providers — mäter policyinlärning, inte modellkvalitet)"
    );

    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(2000);
    let mut policy = BanditPolicy::new(42, 0.2, 0.1);
    let records = train_bandit(&mut policy, &train_questions, 30_000, &tariffs);
    let start = records.len().saturating_sub(100);
    println!(
        "träning: {} beslut av 2000 frågor   reward-medel: första 100 = {:.2}, sista 100 = {:.2}",
        records.len(),
        mean_reward(&records[..100.min(records.len())]),
        mean_reward(&records[start..]),
    );

    policy.set_epsilon(0.0); // fryser utforskningen

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_noisy(500);
    let (a_solved, a_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(SequentialStrategy)
    });
    let (c_solved, c_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(AdaptiveStrategy)
    });
    let eval_policy = policy.clone();
    let (d_solved, d_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, move || {
        Box::new(BanditStrategy::new(eval_policy.clone()))
    });
    println!("500 nya brusiga frågor (held-out):");
    println!(
        "  A sekventiell: {a_solved}/500 lösta, total spend {}",
        format_amount(a_spend)
    );
    println!(
        "  C adaptiv:     {c_solved}/500 lösta, total spend {}",
        format_amount(c_spend)
    );
    println!(
        "  D bandit:      {d_solved}/500 lösta, total spend {}",
        format_amount(d_spend)
    );
}

// ---------------------------------------------------------------------------
// Section 5: the sequential decision — after each scan call the policy
// chooses continue vs escalate. Trained on the noisy corpus; the second
// decision point, targeting the oracle gap (unnecessary scanning).
// ---------------------------------------------------------------------------

fn demo_sequential() {
    let tariffs = swe_gym::strategy::Tariffs {
        scan_milli: 1_000,
        deep_milli: 10_000,
    };

    println!();
    println!("=== F: sekventiellt beslut — fortsätt scanna vs eskalera ===");
    println!("(syntetisk korpus, scriptade providers)");

    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(10_000);
    let mut policy = ScanPolicy::new(1337, 0.2);
    let records = train_sequential(&mut policy, &train_questions, 30_000, &tariffs);
    let start = records.len().saturating_sub(200);
    println!(
        "träning: {} beslut   reward-medel: första 200 = {:.2}, sista 200 = {:.2}",
        records.len(),
        mean_reward_seq(&records[..200.min(records.len())]),
        mean_reward_seq(&records[start..]),
    );

    policy.set_epsilon(0.0); // fryser

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_noisy(500);
    let (a_solved, a_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(SequentialStrategy)
    });
    let (c_solved, c_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(AdaptiveStrategy)
    });
    let eval_policy = policy.clone();
    let (e_solved, e_spend, e_scans) =
        eval_aggregate_seq(&eval_questions, 30_000, &tariffs, move || {
            Box::new(SequentialBanditStrategy::new(eval_policy.clone()))
        });
    // The noisy-world ceiling: the oracle arm, per question (it needs the
    // facit, so it cannot go through the make-closure plumbing).
    let mut oracle_solved = 0;
    let mut oracle_spend = 0u64;
    for question in &eval_questions {
        let mut oracle = OracleStrategy::new(question);
        let report = run_arm(&mut oracle, question, 30_000, &tariffs);
        if report.solved {
            oracle_solved += 1;
        }
        oracle_spend += report.spent_milli;
    }
    println!("500 nya brusiga frågor (held-out):");
    println!(
        "  A sekventiell:    {a_solved}/500 lösta, spend {}",
        format_amount(a_spend)
    );
    println!(
        "  C adaptiv:        {c_solved}/500 lösta, spend {}",
        format_amount(c_spend)
    );
    println!(
        "  E sekv. bandit:   {e_solved}/500 lösta, spend {} (snitt {} scan/fråga)",
        format_amount(e_spend),
        e_scans as f64 / eval_questions.len() as f64,
    );
    println!(
        "  C* orakel [tak]:  {oracle_solved}/500 lösta, spend {}",
        format_amount(oracle_spend),
    );
}

fn mean_reward_seq(records: &[swe_gym::bandit::SeqTrainingRecord]) -> f64 {
    if records.is_empty() {
        return 0.0;
    }
    records.iter().map(|record| record.reward).sum::<f64>() / records.len() as f64
}

fn eval_aggregate_seq(
    questions: &[Question],
    total_budget: u64,
    tariffs: &swe_gym::strategy::Tariffs,
    make: impl FnMut() -> Box<dyn Strategy>,
) -> (usize, u64, usize) {
    let mut solved = 0;
    let mut spend = 0;
    let mut scans = 0;
    let mut make = make;
    for question in questions {
        let mut strategy = make();
        let report = run_arm(strategy.as_mut(), question, total_budget, tariffs);
        if report.solved {
            solved += 1;
        }
        spend += report.spent_milli;
        scans += report
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
    }
    (solved, spend, scans)
}

// ---------------------------------------------------------------------------
// Section 6: TD(0) Sarsa over the scan checkpoint chain — the proper
// sequential-RL step. Q values propagate backward from the terminal reward.
// ---------------------------------------------------------------------------

fn demo_td() {
    let tariffs = swe_gym::strategy::Tariffs {
        scan_milli: 1_000,
        deep_milli: 10_000,
    };

    println!();
    println!("=== G: TD(0) Sarsa över scan-kedjan (ε=0.2, α=0.1, γ=0.95) ===");
    println!("(syntetisk korpus, scriptade providers)");

    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(10_000);
    let mut policy = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    let records = train_td(&mut policy, &train_questions, 30_000, &tariffs);
    let start = records.len().saturating_sub(200);
    println!(
        "träning: {} uppdateringar   slutbelöningsmedel: första 200 = {:.2}, sista 200 = {:.2}",
        records.len(),
        mean_reward_td(&records[..200.min(records.len())]),
        mean_reward_td(&records[start..]),
    );

    policy.set_epsilon(0.0); // fryser

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_noisy(500);
    let (a_solved, a_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(SequentialStrategy)
    });
    let (c_solved, c_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(AdaptiveStrategy)
    });
    let eval_policy = policy.clone();
    let (g_solved, g_spend, g_scans) =
        eval_aggregate_td(&eval_questions, 30_000, &tariffs, move || {
            Box::new(TdSequentialStrategy::new(eval_policy.clone()))
        });
    let mut oracle_solved = 0;
    let mut oracle_spend = 0u64;
    for question in &eval_questions {
        let mut oracle = OracleStrategy::new(question);
        let report = run_arm(&mut oracle, question, 30_000, &tariffs);
        if report.solved {
            oracle_solved += 1;
        }
        oracle_spend += report.spent_milli;
    }
    println!("500 nya brusiga frågor (held-out):");
    println!(
        "  A sekventiell:    {a_solved}/500 lösta, spend {}",
        format_amount(a_spend)
    );
    println!(
        "  C adaptiv:        {c_solved}/500 lösta, spend {}",
        format_amount(c_spend)
    );
    println!(
        "  G TD (Sarsa):     {g_solved}/500 lösta, spend {} (snitt {} scan/fråga)",
        format_amount(g_spend),
        g_scans as f64 / eval_questions.len() as f64,
    );
    println!(
        "  C* orakel [tak]:  {oracle_solved}/500 lösta, spend {}",
        format_amount(oracle_spend),
    );
}

fn mean_reward_td(records: &[swe_gym::td::TdTrainingRecord]) -> f64 {
    if records.is_empty() {
        return 0.0;
    }
    records.iter().map(|record| record.reward).sum::<f64>() / records.len() as f64
}

fn eval_aggregate_td(
    questions: &[Question],
    total_budget: u64,
    tariffs: &swe_gym::strategy::Tariffs,
    make: impl FnMut() -> Box<dyn Strategy>,
) -> (usize, u64, usize) {
    let mut solved = 0;
    let mut spend = 0;
    let mut scans = 0;
    let mut make = make;
    for question in questions {
        let mut strategy = make();
        let report = run_arm(strategy.as_mut(), question, total_budget, tariffs);
        if report.solved {
            solved += 1;
        }
        spend += report.spent_milli;
        scans += report
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
    }
    (solved, spend, scans)
}

// ---------------------------------------------------------------------------
// Section 7: TD with informative features — the structured corpus. Evidence
// lives in the first half, so scan position is real facit-free information.
// The question: does the learned policy use it and beat arm C's scan-all?
// ---------------------------------------------------------------------------

fn demo_td_structured() {
    let tariffs = swe_gym::strategy::Tariffs {
        scan_milli: 1_000,
        deep_milli: 10_000,
    };

    println!();
    println!("=== H: TD med informativ signal — strukturerad korpus ===");
    println!("(evidens enbart i positioner 0-5; scriptade providers)");

    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_structured_noisy(10_000);
    let mut policy = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    let records = train_td(&mut policy, &train_questions, 30_000, &tariffs);
    let start = records.len().saturating_sub(200);
    println!(
        "träning: {} uppdateringar   slutbelöningsmedel: första 200 = {:.2}, sista 200 = {:.2}",
        records.len(),
        mean_reward_td(&records[..200.min(records.len())]),
        mean_reward_td(&records[start..]),
    );

    policy.set_epsilon(0.0); // fryser

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_structured_noisy(500);
    let (a_solved, a_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(SequentialStrategy)
    });
    let (c_solved, c_spend) = eval_aggregate(&eval_questions, 30_000, &tariffs, || {
        Box::new(AdaptiveStrategy)
    });
    let eval_policy = policy.clone();
    let (g_solved, g_spend, g_scans) =
        eval_aggregate_td(&eval_questions, 30_000, &tariffs, move || {
            Box::new(TdSequentialStrategy::new(eval_policy.clone()))
        });
    let mut oracle_solved = 0;
    let mut oracle_spend = 0u64;
    for question in &eval_questions {
        let mut oracle = OracleStrategy::new(question);
        let report = run_arm(&mut oracle, question, 30_000, &tariffs);
        if report.solved {
            oracle_solved += 1;
        }
        oracle_spend += report.spent_milli;
    }
    println!("500 nya strukturerade frågor (held-out):");
    println!(
        "  A sekventiell:    {a_solved}/500 lösta, spend {}",
        format_amount(a_spend)
    );
    println!(
        "  C adaptiv:        {c_solved}/500 lösta, spend {}",
        format_amount(c_spend)
    );
    println!(
        "  G TD (Sarsa):     {g_solved}/500 lösta, spend {} (snitt {} scan/fråga)",
        format_amount(g_spend),
        g_scans as f64 / eval_questions.len() as f64,
    );
    println!(
        "  C* orakel [tak]:  {oracle_solved}/500 lösta, spend {}",
        format_amount(oracle_spend),
    );
}

// ---------------------------------------------------------------------------
// Section 8: the real bench — 638 real contract chunks, real JEV answers
// (replayed), gold facit from the project's legal-questions suite.
// ---------------------------------------------------------------------------

fn demo_real_bench() {
    let bench = load_bench_file("benchmarks/bench_real_v2.json")
        .expect("real bench must exist — run tools/export_real_bench.py");

    println!();
    println!(
        "=== I: riktig bench — {} frågor, riktiga chunks, riktiga JEV-svar (replay) ===",
        bench.questions.len(),
    );
    for question in &bench.questions {
        let fixture = std::fs::read_to_string(format!(
            "benchmarks/real_fixtures/{}.json",
            question.view.id
        ))
        .expect("real fixture must exist — run capture_real");
        let replay = ReplayProvider::load(&fixture).expect("real fixture must load");

        let mut a = SequentialStrategy;
        let a_report = run_arm_with_provider(
            &mut a,
            question,
            bench.total_budget_milli,
            &bench.tariffs,
            &replay,
        );
        let mut c = AdaptiveStrategy;
        let c_report = run_arm_with_provider(
            &mut c,
            question,
            bench.total_budget_milli,
            &bench.tariffs,
            &replay,
        );
        let mut oracle = OracleStrategy::new(question);
        let cx_report = run_arm_with_provider(
            &mut oracle,
            question,
            bench.total_budget_milli,
            &bench.tariffs,
            &replay,
        );
        println!(
            "{} ({} chunks, krav {})",
            question.view.id,
            question.view.chunks.len(),
            question.view.required_coverage,
        );
        for report in [&a_report, &c_report, &cx_report] {
            print_real_arm(report);
        }
        println!();
    }
    println!(
        "(facit: legal-questions-v1 gold; riktig JEV: 100 % gold-träffar, 0 missar på alla fem)"
    );
}

fn print_real_arm(report: &ArmReport) {
    let solved = if report.solved { "LÖST " } else { "OLÖST" };
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
    let label = if report.diagnostic {
        format!("{} [tak]", report.strategy)
    } else {
        report.strategy.to_string()
    };
    println!(
        "  {:<28} {}  spend {}  scan {} deep {}  fynd: {}",
        label,
        solved,
        format_amount(report.spent_milli),
        scan_calls,
        deep_calls,
        report.found.len(),
    );
    if let Some(error) = &report.error {
        println!("  fel: {error}");
    }
}

// ---------------------------------------------------------------------------
// Question labels (derived from the facit, harness-side only).
// ---------------------------------------------------------------------------

fn question_label(question: &Question) -> &'static str {
    if question.scan_blind.is_empty() {
        "scan ser alla chunks"
    } else {
        "scan blind för chunk-07"
    }
}

// ---------------------------------------------------------------------------
// Output helpers.
// ---------------------------------------------------------------------------

/// The experiment's ground truth: which chunks contain evidence. Known only to
/// the demo/driver, never to the workflow definition.
fn ground_truth(chunk: &str) -> Option<bool> {
    match chunk {
        "chunk-01" | "chunk-05" | "chunk-07" => Some(true),
        _ => Some(false),
    }
}

fn print_report(label: &str, report: &RunReport) {
    println!("=== {label} ===");
    for call in &report.calls {
        println!(
            "  {:<9} -> {:<5} spend {}",
            call.chunk,
            call.choice,
            format_amount(call.cost_milli)
        );
    }
    for chunk in &report.denied {
        println!("  {chunk:<9} -> NEKAD — budget uttömd");
    }
    let found = report
        .calls
        .iter()
        .filter(|call| call.choice == "fynd")
        .count();
    println!(
        "  status: {:<10} analyserade: {:>2}   fynd: {}/3   spend: {}   available: {}",
        report.status.as_str(),
        report.calls.len(),
        found,
        format_amount(report.spent_milli),
        format_amount(report.available_milli),
    );
    if let Some(error) = &report.error {
        println!("  fel: {error}");
    }
    println!(
        "  händelser: kernel {}   ledger {} ({})",
        report.machine_events,
        report.ledger_events,
        summarize_kinds(&report.ledger),
    );
    println!();
}

fn print_arm_report(report: &ArmReport) {
    let solved = if report.solved { "LÖST " } else { "OLÖST" };
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
    let label = if report.diagnostic {
        format!("{} [tak]", report.strategy)
    } else {
        report.strategy.to_string()
    };
    println!(
        "  {:<26} {}   spend {}  kvar {}  anrop: scan {} deep {}  nekade: {}  fynd: [{}]",
        label,
        solved,
        format_amount(report.spent_milli),
        format_amount(report.leftover_milli),
        scan_calls,
        deep_calls,
        report.denied.len(),
        report.found.join(", "),
    );
}

fn summarize_kinds(ledger: &Ledger) -> String {
    let mut counts: HashMap<&'static str, u64> = HashMap::new();
    for event in ledger.events() {
        let name = match event.kind {
            EventKind::Allocate => "allocate",
            EventKind::Reserve => "reserve",
            EventKind::Spend => "spend",
            EventKind::Release => "release",
            EventKind::Transfer => "transfer",
            EventKind::Reward => "reward",
        };
        *counts.entry(name).or_default() += 1;
    }
    let mut parts: Vec<String> = counts
        .into_iter()
        .map(|(name, count)| format!("{name} {count}"))
        .collect();
    parts.sort();
    parts.join(", ")
}

fn format_amount(milli: u64) -> String {
    format!("{}.{:03}", milli / 1_000, milli % 1_000)
}
