//! Bandit tests: deterministic generator, SGD behavior, and the first
//! end-to-end learning claim — the trained policy solves the frozen bench
//! (held-out) as well as arm C, from synthetic training data only.

use swe_gym::bandit::{
    train_bandit, train_sequential, Action, BanditPolicy, BanditStrategy, Context, ScanPolicy,
    SequentialBanditStrategy,
};
use swe_gym::bench::load_bench;
use swe_gym::benchmark::run_arm;
use swe_gym::gen::QuestionGenerator;
use swe_gym::strategy::{AdaptiveStrategy, Question, SequentialStrategy, Tariffs};

const FROZEN: &str = include_str!("../benchmarks/bench_v1.json");
const BUDGET: u64 = 30_000;

fn tariffs() -> Tariffs {
    load_bench(FROZEN).unwrap().tariffs
}

fn bench_questions() -> Vec<Question> {
    load_bench(FROZEN).unwrap().questions
}

#[test]
fn generator_is_deterministic_per_seed() {
    let mut a = QuestionGenerator::new(7);
    let mut b = QuestionGenerator::new(7);
    assert_eq!(a.generate(50), b.generate(50));
    let mut c = QuestionGenerator::new(8);
    assert_ne!(a.generate(50), c.generate(50));
}

#[test]
fn generated_questions_need_escalation() {
    let mut generator = QuestionGenerator::new(7);
    for question in generator.generate(100) {
        assert_eq!(question.view.required_coverage, question.evidence.len());
        assert!(!question.scan_blind.is_empty());
        assert!(question
            .scan_blind
            .iter()
            .all(|chunk| question.evidence.contains(chunk)));
    }
}

#[test]
fn policy_update_moves_value_toward_reward() {
    let mut policy = BanditPolicy::new(1, 0.0, 0.1);
    let context = Context {
        features: [1.0, 1.0, 0.45, 0.1, 0.1, 2.0],
    };
    // Optimistic init inflates the first estimate, so the meaningful
    // assertion is convergence: every update moves the estimate toward the
    // observed reward.
    let before = policy.value(Action::Deep1, &context);
    policy.update(&context, Action::Deep1, 9.0);
    let after_positive = policy.value(Action::Deep1, &context);
    assert!((after_positive - 9.0).abs() < (before - 9.0).abs());
    policy.update(&context, Action::Deep1, -1.0);
    let after_negative = policy.value(Action::Deep1, &context);
    assert!((after_negative + 1.0).abs() < (after_positive + 1.0).abs());
}

#[test]
fn trained_bandit_solves_frozen_bench_like_arm_c() {
    let tariffs = tariffs();
    let mut generator = QuestionGenerator::new(7);
    let train_questions = generator.generate(300);
    let mut policy = BanditPolicy::new(42, 0.2, 0.1);
    let records = train_bandit(&mut policy, &train_questions, BUDGET, &tariffs);
    // Every generated question needs escalation, so every run logs a decision.
    assert_eq!(records.len(), 300);
    policy.set_epsilon(0.0);

    let questions = bench_questions();
    let mut easy_bandit = BanditStrategy::new(policy.clone());
    let easy_report = run_arm(&mut easy_bandit, &questions[0], BUDGET, &tariffs);
    let mut hard_bandit = BanditStrategy::new(policy.clone());
    let hard_report = run_arm(&mut hard_bandit, &questions[1], BUDGET, &tariffs);

    // Q1 solves in the scan pass (no bandit decision): 6 coins, like A and C.
    assert!(easy_report.solved);
    assert_eq!(easy_report.spent_milli, 6_000);
    // Q2 needs escalation: the learned policy authorizes deep calls and
    // reaches the same result as arm C — one deep call on chunk-07.
    assert!(hard_report.solved);
    assert_eq!(hard_report.spent_milli, 20_000);
    let deep_calls: Vec<&swe_gym::driver::CallRecord> = hard_report
        .calls
        .iter()
        .filter(|call| call.provider == "deep")
        .collect();
    assert_eq!(deep_calls.len(), 1);
    assert_eq!(deep_calls[0].chunk, "chunk-07");
}

#[test]
fn training_is_reproducible() {
    let tariffs = tariffs();
    let mut g1 = QuestionGenerator::new(7);
    let t1 = g1.generate(200);
    let mut g2 = QuestionGenerator::new(7);
    let t2 = g2.generate(200);
    assert_eq!(t1, t2);

    let mut p1 = BanditPolicy::new(42, 0.2, 0.1);
    let mut p2 = BanditPolicy::new(42, 0.2, 0.1);
    let rec1 = train_bandit(&mut p1, &t1, BUDGET, &tariffs);
    let rec2 = train_bandit(&mut p2, &t2, BUDGET, &tariffs);
    assert_eq!(rec1, rec2);
}

#[test]
fn score_model_v2_is_deterministic_and_noisy() {
    let mut generator = QuestionGenerator::new(7);
    let questions = generator.generate_noisy(200);
    let mut again = QuestionGenerator::new(7);
    assert_eq!(again.generate_noisy(200), questions);

    let mut blind_scores: Vec<u32> = Vec::new();
    let mut negative_scores: Vec<u32> = Vec::new();
    for question in &questions {
        assert!(question.noise_seed > 0);
        assert!(question.budget_milli >= 20_000 && question.budget_milli <= 40_000);
        let corpus = question.corpus();
        for chunk in &question.view.chunks {
            let score = corpus.scan_score(chunk);
            assert!(score <= 10_000);
            if question.scan_blind.contains(chunk) {
                blind_scores.push(score);
            } else if !question.evidence.contains(chunk) {
                negative_scores.push(score);
            }
        }
    }
    let spread = |scores: &[u32]| scores.iter().max().unwrap() - scores.iter().min().unwrap();
    assert!(spread(&blind_scores) > 2_000, "blind scores must vary");
    assert!(
        spread(&negative_scores) > 1_000,
        "negative scores must vary"
    );
    // Ranking ambiguity must exist: some blind chunk scores below a negative.
    let max_negative = *negative_scores.iter().max().unwrap();
    assert!(
        blind_scores.iter().any(|score| *score < max_negative),
        "the v2 signal must be genuinely ambiguous"
    );
}

#[test]
fn sequential_bandit_learns_arm_c_behavior_with_episodic_credit() {
    let tariffs = tariffs();
    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(4_000);
    let mut policy = ScanPolicy::new(1337, 0.2);
    let records = train_sequential(&mut policy, &train_questions, BUDGET, &tariffs);
    assert!(records.len() > 10_000, "many sequential decisions");
    policy.set_epsilon(0.0);

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_noisy(500);
    let mut e_solved = 0;
    let mut e_spend = 0u64;
    let mut c_solved = 0;
    let mut c_spend = 0u64;
    for question in &eval_questions {
        let mut sequential = SequentialBanditStrategy::new(policy.clone());
        let sequential_report = run_arm(&mut sequential, question, BUDGET, &tariffs);
        let adaptive_report = run_arm(&mut AdaptiveStrategy, question, BUDGET, &tariffs);
        if sequential_report.solved {
            e_solved += 1;
        }
        e_spend += sequential_report.spent_milli;
        if adaptive_report.solved {
            c_solved += 1;
        }
        c_spend += adaptive_report.spent_milli;
    }
    // With episodic credit the sequential policy converges to arm C's
    // behavior — the hand rule rediscovered from data. It must stay within
    // 10% of C's solve rate and 10% of C's spend.
    assert!(
        e_solved * 10 >= c_solved * 9,
        "E {} vs C {}",
        e_solved,
        c_solved,
    );
    assert!(
        e_spend <= c_spend + c_spend / 10,
        "E {} vs C {}",
        e_spend,
        c_spend,
    );
}

#[test]
fn noisy_training_generalizes_to_heldout() {
    let tariffs = tariffs();
    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(2000);
    let mut policy = BanditPolicy::new(42, 0.2, 0.1);
    let records = train_bandit(&mut policy, &train_questions, BUDGET, &tariffs);
    assert!(
        records.len() > 1000,
        "most noisy questions must need a decision"
    );
    policy.set_epsilon(0.0);

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate_noisy(500);
    let mut bandit_solved = 0;
    let mut bandit_spend = 0u64;
    let mut adaptive_solved = 0;
    let mut adaptive_spend = 0u64;
    let mut sequential_solved = 0;
    let mut sequential_spend = 0u64;
    for question in &eval_questions {
        let mut bandit = BanditStrategy::new(policy.clone());
        let bandit_report = run_arm(&mut bandit, question, BUDGET, &tariffs);
        let adaptive_report = run_arm(&mut AdaptiveStrategy, question, BUDGET, &tariffs);
        let sequential_report = run_arm(&mut SequentialStrategy, question, BUDGET, &tariffs);
        if bandit_report.solved {
            bandit_solved += 1;
        }
        bandit_spend += bandit_report.spent_milli;
        if adaptive_report.solved {
            adaptive_solved += 1;
        }
        adaptive_spend += adaptive_report.spent_milli;
        if sequential_report.solved {
            sequential_solved += 1;
        }
        sequential_spend += sequential_report.spent_milli;
    }
    // In the noisy world the arms land on different points of the
    // quality-cost frontier. The learned policy trades absolute solve rate
    // for efficiency — that is a legitimate learned operating point, and it
    // must dominate the hand-coded adaptive rule on the experiment's north
    // star: verified quality per Sweycoin.
    let quality = |solved: usize, spend: u64| solved as f64 / spend.max(1) as f64;
    let bandit_quality = quality(bandit_solved, bandit_spend);
    let adaptive_quality = quality(adaptive_solved, adaptive_spend);
    let sequential_quality = quality(sequential_solved, sequential_spend);
    assert!(
        adaptive_solved > sequential_solved,
        "arm C must beat A on solve rate: C {} vs A {}",
        adaptive_solved,
        sequential_solved,
    );
    assert!(
        bandit_quality >= adaptive_quality,
        "bandit quality {bandit_quality:.5} must beat C {adaptive_quality:.5} per coin",
    );
    assert!(
        adaptive_quality > sequential_quality,
        "C quality {adaptive_quality:.5} must beat A {sequential_quality:.5} per coin",
    );
    // No catastrophic solve-rate collapse: within 60% of C.
    assert!(
        bandit_solved * 5 >= adaptive_solved * 3,
        "bandit {} vs C {}",
        bandit_solved,
        adaptive_solved,
    );
}

#[test]
fn greedy_policy_is_deterministic_across_runs() {
    let tariffs = tariffs();
    let mut generator = QuestionGenerator::new(7);
    let train_questions = generator.generate(300);
    let mut policy = BanditPolicy::new(42, 0.2, 0.1);
    train_bandit(&mut policy, &train_questions, BUDGET, &tariffs);
    policy.set_epsilon(0.0);

    let questions = bench_questions();
    let hard = &questions[1];
    let mut first = BanditStrategy::new(policy.clone());
    let r1 = run_arm(&mut first, hard, BUDGET, &tariffs);
    let mut second = BanditStrategy::new(policy.clone());
    let r2 = run_arm(&mut second, hard, BUDGET, &tariffs);
    assert_eq!(r1.spent_milli, r2.spent_milli);
    assert_eq!(r1.found, r2.found);
    assert_eq!(r1.calls.len(), r2.calls.len());
}

#[test]
fn trained_bandit_matches_adaptive_on_generated_heldout() {
    let tariffs = tariffs();
    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate(300);
    let mut policy = BanditPolicy::new(42, 0.2, 0.1);
    train_bandit(&mut policy, &train_questions, BUDGET, &tariffs);
    policy.set_epsilon(0.0);

    let mut eval_generator = QuestionGenerator::new(99);
    let eval_questions = eval_generator.generate(100);
    let mut bandit_solved = 0;
    let mut bandit_spend = 0u64;
    let mut adaptive_solved = 0;
    let mut adaptive_spend = 0u64;
    for question in &eval_questions {
        let mut bandit = BanditStrategy::new(policy.clone());
        let bandit_report = run_arm(&mut bandit, question, BUDGET, &tariffs);
        let adaptive_report = run_arm(&mut AdaptiveStrategy, question, BUDGET, &tariffs);
        if bandit_report.solved {
            bandit_solved += 1;
        }
        bandit_spend += bandit_report.spent_milli;
        if adaptive_report.solved {
            adaptive_solved += 1;
        }
        adaptive_spend += adaptive_report.spent_milli;
    }
    // Arm C solves everything on this corpus; the learned policy must match
    // it exactly — same solves, same spend — without ever seeing the facit.
    assert_eq!(adaptive_solved, 100);
    assert_eq!(bandit_solved, 100);
    assert_eq!(bandit_spend, adaptive_spend);
}
