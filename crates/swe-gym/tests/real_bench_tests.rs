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

    // The learned policies now scan in the measured retrieval order, like
    // arm H. Expected scan counts per question (pinned with arm H).
    let expected: &[(&str, usize)] = &[
        ("auto-renewal", 38),
        ("notice-period", 26),
        ("liability-cap", 47),
        ("confidentiality", 18),
        ("liability-secrecy-carveout", 16),
    ];
    for (question, (qid, h_scans)) in bench.questions.iter().zip(expected) {
        assert_eq!(question.view.id, *qid);
        let fixture = std::fs::read_to_string(format!(
            "benchmarks/real_fixtures/{}.json",
            question.view.id
        ))
        .unwrap();
        let replay = ReplayProvider::load(&fixture).unwrap();
        let mut e = SequentialBanditStrategy::new(scan_policy.clone());
        let e_report = run_arm_with_provider(&mut e, question, 2_000_000, &tariffs, &replay);
        let mut g = TdSequentialStrategy::new(td_policy.clone());
        let g_report = run_arm_with_provider(&mut g, question, 2_000_000, &tariffs, &replay);
        // The learned stop/budget policies tie arm H exactly: on the real
        // bench the remaining H->oracle gap is ranking imperfection, not
        // decision policy — there is nothing left to learn on this decision
        // surface. And they still do not collapse out of distribution.
        for report in [&e_report, &g_report] {
            assert!(report.solved, "{} must solve via scan", question.view.id);
            assert_eq!(
                report.calls.iter().filter(|c| c.provider == "scan").count(),
                *h_scans,
                "{}: transferred policy must scan like arm H",
                question.view.id,
            );
        }
    }
}

#[test]
fn retrieval_index_capital_cost_amortizes_immediately() {
    // The retrieval index is a one-time capital cost, measured with
    // --force in tools/embed_analysis.py. Under the calibration anchor
    // (1 Sweycoin = 1000 tokens or 1 second) the index costs
    // ceil(max(tokens, ms)/1000) coins once; arm H's per-question savings
    // must exceed it, so the break-even is below one question.
    let source = include_str!("../benchmarks/real_embedding_report.json");
    let json = swe_native::parse_json_str(source).unwrap();
    let index = json.get("index").unwrap();
    let tokens = index
        .get("total_tokens")
        .and_then(swe_native::Json::as_number)
        .and_then(|n| n.as_u64())
        .unwrap();
    let latency_ms = index
        .get("latency_ms")
        .and_then(swe_native::Json::as_number)
        .and_then(|n| n.as_u64())
        .unwrap();
    let index_coins = ((tokens as f64 / 1_000.0).max(latency_ms as f64 / 1_000.0)).ceil() as u64;
    assert_eq!(index_coins, 78, "measured index cost under the anchor");

    // Pinned arm A vs arm H scan counts per question.
    let per_question: &[(&str, usize, usize)] = &[
        ("auto-renewal", 568, 38),
        ("notice-period", 320, 26),
        ("liability-cap", 525, 48),
        ("confidentiality", 179, 18),
        ("liability-secrecy-carveout", 244, 16),
    ];
    for (qid, a_scans, h_scans) in per_question {
        let savings = (a_scans - h_scans) as u64;
        assert!(
            savings > index_coins,
            "{qid}: H saves {savings} coins, index costs {index_coins} — must amortize immediately",
        );
    }
}

#[test]
fn two_phase_scanner_beats_blind_scan_on_all_real_questions() {
    use swe_gym::strategy::SimilarityOrderStrategy;
    let bench = load_bench(REAL_BENCH).expect("real bench must load");
    // Measured arm H scan counts per question, pinned.
    let expected: &[(&str, usize)] = &[
        ("auto-renewal", 38),
        ("notice-period", 26),
        ("liability-cap", 47),
        ("confidentiality", 18),
        ("liability-secrecy-carveout", 16),
    ];
    for (question, (qid, h_scans)) in bench.questions.iter().zip(expected) {
        assert_eq!(question.view.id, *qid);
        let source =
            std::fs::read_to_string(format!("benchmarks/real_fixtures/{qid}.json")).unwrap();
        let replay = ReplayProvider::load(&source).unwrap();
        let mut a = swe_gym::strategy::SequentialStrategy;
        let a_report = run_arm_with_provider(&mut a, question, 2_000_000, &bench.tariffs, &replay);
        let mut h = SimilarityOrderStrategy;
        let h_report = run_arm_with_provider(&mut h, question, 2_000_000, &bench.tariffs, &replay);
        let h_scans_actual = h_report
            .calls
            .iter()
            .filter(|call| call.provider == "scan")
            .count();
        assert!(h_report.solved, "{qid}: arm H must solve");
        assert_eq!(h_scans_actual, *h_scans, "{qid}: arm H scan count");
        // The whole point: the retrieval-ordered scan cuts the blind scan
        // by an order of magnitude and sits within 2.5x of the oracle.
        assert!(
            h_scans_actual * 3 < a_report.calls.len(),
            "{qid}: H {h_scans_actual} must beat A {} clearly",
            a_report.calls.len(),
        );
        assert!(
            h_scans_actual <= question.view.required_coverage * 2 + 10,
            "{qid}: H {h_scans_actual} must stay near the oracle {}",
            question.view.required_coverage,
        );
    }
}

#[test]
fn embedding_report_pins_the_information_content() {
    let source = include_str!("../benchmarks/real_embedding_report.json");
    let json = swe_native::parse_json_str(source).unwrap();
    let questions = json
        .get("questions")
        .and_then(swe_native::Json::as_array)
        .expect("report questions");
    assert_eq!(questions.len(), 5);
    for question in questions {
        let id = question
            .get("id")
            .and_then(swe_native::Json::as_str)
            .unwrap();
        let get = |key: &str| {
            question
                .get(key)
                .and_then(swe_native::Json::as_number)
                .and_then(|n| n.as_u64())
                .unwrap() as usize
        };
        let doc = get("scans_document_order");
        let jev = get("scans_jev_score_order");
        let sim = get("scans_similarity_order");
        let oracle = get("oracle_scans");
        // The three signals, ranked: embedding similarity beats blind
        // document order by a wide margin; JEV's own scores beat similarity
        // and sit near the oracle floor.
        assert!(
            sim < doc,
            "{id}: similarity {sim} must beat document order {doc}"
        );
        assert!(
            jev <= sim,
            "{id}: JEV scores {jev} must beat similarity {sim}"
        );
        assert!(jev <= oracle * 2, "{id}: JEV {jev} near oracle {oracle}");
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
