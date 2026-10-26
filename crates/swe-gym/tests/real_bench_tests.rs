//! Real-bench pins: the exported auto-renewal bench and its live JEV
//! fixture are frozen artifacts — a silent edit breaks CI, like the
//! synthetic bench before them.

use swe_gym::bench::load_bench;
use swe_gym::benchmark::run_arm_with_provider;
use swe_gym::provider::{ReplayProvider, ResearchProvider};

const REAL_BENCH: &str = include_str!("../benchmarks/bench_real_v2.json");
const REAL_FIXTURE: &str = include_str!("../benchmarks/real_fixtures/auto-renewal.json");

#[test]
fn real_bench_is_frozen_and_complete() {
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    assert_eq!(bench.name, "swe-gym-real-legal-v1");
    assert_eq!(bench.questions.len(), 5);
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
    // The other four questions: non-empty, with their own evidence and
    // classify question text.
    for question in &bench.questions[1..] {
        assert!(!question.view.chunks.is_empty());
        assert!(!question.evidence.is_empty());
        assert!(
            !question.view.question.is_empty(),
            "{} must carry its classify question",
            question.view.id,
        );
    }
}

#[test]
fn real_fixtures_are_frozen_and_match_gold() {
    // Measured JEV behavior on the project's corpus, per question:
    // (id, chunks, gold evidence, JEV fynd, true positives, extra fynd).
    let expected: &[(&str, usize, usize, usize, usize, usize)] = &[
        ("auto-renewal", 638, 20, 22, 20, 2),
        ("notice-period", 408, 13, 15, 13, 2),
        ("liability-cap", 877, 34, 51, 34, 17),
        ("confidentiality", 419, 13, 23, 13, 10),
        ("liability-secrecy-carveout", 315, 7, 7, 7, 0),
    ];
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    assert_eq!(bench.questions.len(), expected.len());
    for (question, (qid, chunks, gold, _fynd, tp, fp)) in bench.questions.iter().zip(expected) {
        assert_eq!(question.view.id, *qid);
        assert_eq!(question.view.chunks.len(), *chunks, "{qid} chunks");
        assert_eq!(question.evidence.len(), *gold, "{qid} gold");
        let source = std::fs::read_to_string(format!("benchmarks/real_fixtures/{qid}.json"))
            .unwrap_or_else(|error| panic!("fixture missing for {qid}: {error}"));
        let replay = ReplayProvider::load(&source).unwrap();
        assert_eq!(replay.len(), *chunks, "{qid} fixture size");
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
        // Real JEV finds every gold chunk on all five questions; the false
        // positives vary with question specificity. Pinned.
        assert_eq!(gold_found, *tp, "{qid}: JEV must find all gold evidence");
        assert_eq!(extra_fynd, *fp, "{qid}: measured extra fynd count");
    }
}

#[test]
fn synthetic_trained_policies_transfer_to_real_questions() {
    use swe_gym::bandit::{train_sequential, ScanPolicy, SequentialBanditStrategy};
    use swe_gym::gen::QuestionGenerator;
    use swe_gym::td::{train_td, TdPolicy, TdSequentialStrategy};
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    let tariffs = bench.tariffs;

    // Train the two sequential policies on the synthetic noisy corpus.
    let mut train_generator = QuestionGenerator::new(7);
    let train_questions = train_generator.generate_noisy(4_000);
    let mut scan_policy = ScanPolicy::new(1337, 0.2);
    train_sequential(&mut scan_policy, &train_questions, 30_000, &tariffs);
    scan_policy.set_epsilon(0.0);
    let mut td_policy = TdPolicy::new(4242, 0.2, 0.1, 0.95);
    train_td(&mut td_policy, &train_questions, 30_000, &tariffs);
    td_policy.set_epsilon(0.0);

    for question in &bench.questions {
        let fixture = std::fs::read_to_string(format!(
            "benchmarks/real_fixtures/{}.json",
            question.view.id
        ))
        .unwrap();
        let replay = ReplayProvider::load(&fixture).unwrap();
        let mut a = swe_gym::strategy::SequentialStrategy;
        let a_report = run_arm_with_provider(&mut a, question, 2_000_000, &tariffs, &replay);
        let mut e = SequentialBanditStrategy::new(scan_policy.clone());
        let e_report = run_arm_with_provider(&mut e, question, 2_000_000, &tariffs, &replay);
        let mut g = TdSequentialStrategy::new(td_policy.clone());
        let g_report = run_arm_with_provider(&mut g, question, 2_000_000, &tariffs, &replay);
        // Transfer safety: the synthetic-trained sequential policies must
        // not collapse into pathological early escalation on real
        // out-of-distribution contexts. Measured: both solve every real
        // question with exactly arm A's scan count.
        for report in [&e_report, &g_report] {
            assert!(report.solved, "{} must solve via scan", question.view.id);
            assert_eq!(
                report.calls.iter().filter(|c| c.provider == "scan").count(),
                a_report
                    .calls
                    .iter()
                    .filter(|c| c.provider == "scan")
                    .count(),
                "{}: transferred policy must scan like arm A",
                question.view.id,
            );
        }
    }
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
