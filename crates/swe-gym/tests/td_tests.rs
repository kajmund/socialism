//! TD(0) Sarsa tests: the bootstrapped update, reproducibility, and the
//! pinned end-to-end result — TD over the scan checkpoints converges to arm
//! C's operating point, which is the optimum for the available facit-free
//! features. The remaining gap to the oracle is knowledge, not policy.

use swe_gym::benchmark::run_arm;
use swe_gym::gen::QuestionGenerator;
use swe_gym::strategy::{AdaptiveStrategy, Tariffs};
use swe_gym::td::{train_td, TdPolicy, TdSequentialStrategy};

const BUDGET: u64 = 30_000;

fn tariffs() -> Tariffs {
    Tariffs {
        scan_milli: 1_000,
        deep_milli: 10_000,
    }
}

#[test]
fn td_update_moves_q_toward_target() {
    let mut policy = TdPolicy::new(1, 0.0, 0.5, 1.0);
    // Terminal update: optimistic 5.0 moves toward the observed reward 8.0.
    policy.update_sarsa(7, 0, None, 8.0);
    assert_eq!(policy.q_value(7, 0), 6.5);
    // Bootstrapped update: target = gamma * Q(next) = 1.0 * 6.5 (the value
    // just updated above), so 5 + 0.5 * (6.5 - 5) = 5.75.
    policy.update_sarsa(3, 0, Some((7, 0)), 8.0);
    assert_eq!(policy.q_value(3, 0), 5.75);
    assert_eq!(policy.q_value(7, 1), 5.0); // untouched action
}

#[test]
fn td_training_is_reproducible() {
    let tariffs = tariffs();
    let mut g1 = QuestionGenerator::new(7);
    let t1 = g1.generate_noisy(500);
    let mut g2 = QuestionGenerator::new(7);
    let t2 = g2.generate_noisy(500);
    assert_eq!(t1, t2);

    let mut p1 = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    let mut p2 = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    let rec1 = train_td(&mut p1, &t1, BUDGET, &tariffs);
    let rec2 = train_td(&mut p2, &t2, BUDGET, &tariffs);
    assert_eq!(rec1, rec2);
}

#[test]
fn structured_generator_clusters_evidence_in_the_first_half() {
    let mut generator = QuestionGenerator::new(7);
    let questions = generator.generate_structured_noisy(100);
    let mut again = QuestionGenerator::new(7);
    assert_eq!(again.generate_structured_noisy(100), questions);
    for question in &questions {
        for chunk in &question.evidence {
            let position = question
                .view
                .chunks
                .iter()
                .position(|candidate| candidate == chunk)
                .unwrap();
            assert!(position < 5, "evidence must live in the first half");
        }
        assert!(question.noise_seed > 0);
    }
}

#[test]
fn td_with_position_signal_beats_arm_c_on_structured_heldout() {
    let tariffs = tariffs();
    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_structured_noisy(4_000);
    let mut policy = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    let records = train_td(&mut policy, &train_questions, BUDGET, &tariffs);
    assert!(records.len() > 10_000, "many sequential updates");
    policy.set_epsilon(0.0);

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_structured_noisy(500);
    let mut g_solved = 0;
    let mut g_spend = 0u64;
    let mut g_scans = 0usize;
    let mut c_solved = 0;
    let mut c_spend = 0u64;
    for question in &eval_questions {
        let mut td_strategy = TdSequentialStrategy::new(policy.clone());
        let td_report = run_arm(&mut td_strategy, question, BUDGET, &tariffs);
        let adaptive_report = run_arm(&mut AdaptiveStrategy, question, BUDGET, &tariffs);
        if td_report.solved {
            g_solved += 1;
        }
        g_spend += td_report.spent_milli;
        g_scans += td_report
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
        if adaptive_report.solved {
            c_solved += 1;
        }
        c_spend += adaptive_report.spent_milli;
    }
    // The headline of the feature experiment: with scan position as a real
    // signal, the learned policy stops scanning past the evidence region —
    // beating the hand rule on both axes. It solves at least as many, spends
    // less, and scans clearly fewer chunks.
    assert!(g_solved >= c_solved, "TD {} vs C {}", g_solved, c_solved);
    assert!(g_spend < c_spend, "TD {} vs C {}", g_spend, c_spend);
    let g_avg_scans = g_scans as f64 / eval_questions.len() as f64;
    assert!(
        g_avg_scans < 8.0,
        "TD must stop early: {g_avg_scans:.2} scans"
    );
}

#[test]
fn td_policy_matches_arm_c_on_noisy_heldout() {
    let tariffs = tariffs();
    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(4_000);
    let mut policy = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    let records = train_td(&mut policy, &train_questions, BUDGET, &tariffs);
    assert!(records.len() > 10_000, "many sequential updates");
    policy.set_epsilon(0.0);

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_noisy(500);
    let mut g_solved = 0;
    let mut g_spend = 0u64;
    let mut c_solved = 0;
    let mut c_spend = 0u64;
    for question in &eval_questions {
        let mut td_strategy = TdSequentialStrategy::new(policy.clone());
        let td_report = run_arm(&mut td_strategy, question, BUDGET, &tariffs);
        let adaptive_report = run_arm(&mut AdaptiveStrategy, question, BUDGET, &tariffs);
        if td_report.solved {
            g_solved += 1;
        }
        g_spend += td_report.spent_milli;
        if adaptive_report.solved {
            c_solved += 1;
        }
        c_spend += adaptive_report.spent_milli;
    }
    // TD converges to C's operating point — the optimum for the available
    // facit-free features. The assertions pin that convergence.
    assert!(
        g_solved * 10 >= c_solved * 9,
        "TD {} vs C {}",
        g_solved,
        c_solved,
    );
    assert!(
        g_spend <= c_spend + c_spend / 10,
        "TD {} vs C {}",
        g_spend,
        c_spend
    );
}
