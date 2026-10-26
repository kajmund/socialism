//! Provider layer tests: the score model behind the trait, JEV answer
//! mapping, and replay/record round-trips. All offline.

use swe_gym::provider::{
    json_escape, map_jev_choice, RecordProvider, ReplayProvider, ResearchProvider,
};
use swe_gym::strategy::{FakeCorpus, Question, QuestionView};
use swe_native::parse_json_str;

fn corpus(evidence: &[&str], blind: &[&str]) -> FakeCorpus {
    Question {
        view: QuestionView {
            id: "t".into(),
            chunks: vec![],
            required_coverage: 0,
        },
        evidence: evidence.iter().map(|chunk| chunk.to_string()).collect(),
        scan_blind: blind.iter().map(|chunk| chunk.to_string()).collect(),
        noise_seed: 0,
        budget_milli: 0,
        texts: std::collections::HashMap::new(),
    }
    .corpus()
}

#[test]
fn corpus_provider_keeps_score_model_v1_behind_the_trait() {
    let corpus = corpus(&["chunk-01", "chunk-05", "chunk-07"], &["chunk-07"]);
    // Visible evidence: fynd at 9000.
    let answer = corpus.analyze("scan", "chunk-01", "").unwrap();
    assert_eq!(answer.choice, "fynd");
    assert_eq!(answer.score_bp, 9_000);
    // Blind evidence: inget at 4500 — the suspicious signal.
    let answer = corpus.analyze("scan", "chunk-07", "").unwrap();
    assert_eq!(answer.choice, "inget");
    assert_eq!(answer.score_bp, 4_500);
    // Clear negative.
    let answer = corpus.analyze("scan", "chunk-03", "").unwrap();
    assert_eq!(answer.choice, "inget");
    assert_eq!(answer.score_bp, 1_000);
    // Deep sees everything.
    let answer = corpus.analyze("deep", "chunk-07", "").unwrap();
    assert_eq!(answer.choice, "fynd");
    assert_eq!(answer.score_bp, 9_900);
}

#[test]
fn jev_answer_mapping_follows_the_convention() {
    let row = |json: &str| parse_json_str(json).unwrap();
    // YES 1.0 → fynd 10000 (the live smoke shape).
    let yes = row(r#"{"choice":"YES","confidence":1.0}"#);
    assert_eq!(map_jev_choice(&yes).unwrap(), ("fynd".into(), 10_000));
    // NO 0.8 → inget 1000.
    let no = row(r#"{"choice":"NO","confidence":0.8}"#);
    assert_eq!(map_jev_choice(&no).unwrap(), ("inget".into(), 1_000));
    // UNCERTAIN → inget 4500, the suspicious band.
    let uncertain = row(r#"{"choice":"UNCERTAIN","confidence":0.5}"#);
    assert_eq!(map_jev_choice(&uncertain).unwrap(), ("inget".into(), 4_500));
    // Invalid shapes fail loudly.
    assert!(map_jev_choice(&row(r#"{"choice":"MAYBE","confidence":0.5}"#)).is_err());
    assert!(map_jev_choice(&row(r#"{"choice":"YES","confidence":1.7}"#)).is_err());
    assert!(map_jev_choice(&row(r#"{"confidence":0.5}"#)).is_err());
}

struct Stub;

impl ResearchProvider for Stub {
    fn analyze(
        &self,
        provider: &str,
        chunk_id: &str,
        _text: &str,
    ) -> Result<swe_gym::provider::ProviderAnswer, String> {
        Ok(swe_gym::provider::ProviderAnswer {
            choice: if chunk_id.contains('1') {
                "fynd".into()
            } else {
                "inget".into()
            },
            score_bp: if chunk_id.contains('1') { 9_000 } else { 1_000 },
            latency_ms: 0,
            raw: format!("stub:{provider}:{chunk_id}"),
        })
    }
}

#[test]
fn record_then_replay_round_trips() {
    let stub = Stub;
    let recorder = RecordProvider::new(&stub);
    for chunk in ["chunk-00", "chunk-01", "chunk-02"] {
        recorder.analyze("scan", chunk, "text").unwrap();
    }
    let fixture = recorder.to_fixture("round-trip-test");
    let replay = ReplayProvider::load(&fixture).unwrap();
    assert_eq!(replay.len(), 3);
    let live = recorder.analyze("scan", "chunk-01", "text").unwrap();
    let replayed = replay.analyze("scan", "chunk-01", "text").unwrap();
    assert_eq!(replayed, live);
}

#[test]
fn replay_missing_entry_fails_loudly() {
    let replay = ReplayProvider::load(
        r#"{"source":"t","entries":[{"provider":"scan","chunk_id":"chunk-00","choice":"inget","score_bp":1000,"raw":""}]}"#,
    )
    .unwrap();
    let result = replay.analyze("scan", "chunk-99", "");
    assert!(
        result.is_err(),
        "missing fixture entries must not fabricate answers"
    );
}

#[test]
fn json_escape_handles_quotes_and_controls() {
    assert_eq!(json_escape(r#"a"b\c"#), r#"a\"b\\c"#);
    assert_eq!(json_escape("rad\nrad"), "rad\\nrad");
}

#[test]
fn llm_word_mapping_follows_the_convention() {
    use swe_gym::provider::map_llm_word;
    assert_eq!(map_llm_word("JA").unwrap(), ("fynd".into(), 9_500));
    assert_eq!(map_llm_word("NEJ\n").unwrap(), ("inget".into(), 500));
    assert_eq!(map_llm_word("OSÄKER").unwrap(), ("inget".into(), 4_500));
    assert!(map_llm_word("Kanske").is_err());
}

#[test]
fn replay_provider_rejects_malformed_fixtures() {
    assert!(ReplayProvider::load("{}").is_err());
    assert!(ReplayProvider::load(r#"{"entries":[]}"#).is_err());
    assert!(ReplayProvider::load(r#"{"entries":[{"provider":"scan"}]}"#).is_err());
}

// ---------------------------------------------------------------------------
// The committed live fixture: frozen, loadable, and carrying measured data.
// ---------------------------------------------------------------------------

const LIVE_FIXTURE: &str = include_str!("../benchmarks/jev_fixture_v1.json");

#[test]
fn live_jev_fixture_is_frozen_and_loads() {
    assert!(
        LIVE_FIXTURE.contains("live JEV capture"),
        "fixture source label is part of the frozen artifact"
    );
    assert!(
        LIVE_FIXTURE.contains("förlängs automatiskt"),
        "question label missing"
    );
    let replay = ReplayProvider::load(LIVE_FIXTURE).unwrap();
    // Six chunks x two real providers (JEV scan + Cerebras deep).
    assert_eq!(replay.len(), 12);
    for provider in ["scan", "deep"] {
        for chunk in [
            "chunk-r1", "chunk-r2", "chunk-r3", "chunk-r4", "chunk-r5", "chunk-r6",
        ] {
            let answer = replay.analyze(provider, chunk, "").unwrap();
            assert!(answer.latency_ms > 0, "captured calls carry latency");
            assert!(answer.score_bp <= 10_000);
            let (input, output) = swe_gym::provider::usage_tokens(&answer.raw).unwrap();
            assert!(input > 0 && output > 0, "captured raw payloads carry usage");
            if provider == "deep" {
                assert!(answer.raw.contains("choices"), "LLM payload shape");
            } else {
                assert!(answer.raw.contains("answers"), "JEV payload shape");
            }
        }
    }
}
