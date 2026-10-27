//! One-shot live capture: analyze six fixed chunks through the real JEV
//! provider and write the answers (with latency and raw payloads) to
//! benchmarks/jev_fixture_v1.json. The fixture then powers offline replay
//! runs and tariff calibration — deterministic, no further live calls.
//!
//! Usage: cargo run --example capture_fixture   (costs six small JEV calls)

use swe_gym::provider::{
    resolve_secret, HttpJevProvider, HttpLlmProvider, RecordProvider, ResearchProvider,
};

const CHUNKS: [(&str, &str); 6] = [
    (
        "chunk-r1",
        "Styrelsen får förlänga avtalet automatiskt utan nytt godkännande från parterna.",
    ),
    (
        "chunk-r2",
        "Part ska betala faktura inom trettio dagar från fakturadatum.",
    ),
    (
        "chunk-r3",
        "Om ingen part säger upp avtalet senast tre månader före avtalstidens utgång förlängs det automatiskt med ett år i taget.",
    ),
    (
        "chunk-r4",
        "Leverantören ansvarar för att varan är fri från fel vid tidpunkten för leverans.",
    ),
    (
        "chunk-r5",
        "Avtalet gäller tills vidare och kan sägas upp av endera parten med tre månaders uppsägningstid.",
    ),
    (
        "chunk-r6",
        "Parterna ska behandla avtalets innehåll konfidentiellt under avtalstiden.",
    ),
];

/// The classification question, reused verbatim from the repo's own suite
/// (experiments/overgraph_ingest/.../jev/questions.py, CLASSIFY_QUESTION) —
/// reuse before new. The first generic capture attempt answered YES to
/// everything; a JEV call is only as good as the question it is asked.
const QUESTION: &str = "Innehåller texten en bestämmelse där avtalet förlängs automatiskt utan ett nytt uttryckligt godkännande från båda parterna?";

const INSTRUCTIONS: &str = "Innehåller texten en bestämmelse där avtalet förlängs automatiskt utan ett nytt uttryckligt godkännande från båda parterna? Classify only the candidate `text` field. YES only if the candidate text itself contains the provision asked about. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN. Do not drop UNCERTAIN; it is a valid outcome.";

fn main() {
    let api_key = resolve_secret("TYPESAFE_API_KEY", "../../backend/.env")
        .expect("TYPESAFE_API_KEY saknas (sätt i miljön eller backend/.env)");
    let base_url = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let scan = HttpJevProvider::new(&api_key, &base_url, &model)
        .with_instructions(INSTRUCTIONS)
        .with_criteria(
            "The candidate text itself contains the provision asked about.",
            "The candidate text does not contain that provision.",
            "The supplied text and context are not enough to decide.",
        );

    // Deep = a real LLM (Cerebras, OpenAI-compatible). Same seam, real model.
    let llm_key = resolve_secret("CEREBRAS_API_KEY", "../../backend/.env")
        .expect("CEREBRAS_API_KEY saknas (sätt i miljön eller backend/.env)");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());
    let deep = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du klassificerar avtalstext. Fråga: Innehåller texten en bestämmelse där avtalet förlängs automatiskt utan ett nytt uttryckligt godkännande från båda parterna? Svara med exakt ett ord: JA, NEJ eller OSÄKER.",
    );

    struct ScanDeep {
        scan: HttpJevProvider,
        deep: HttpLlmProvider,
    }
    impl ResearchProvider for ScanDeep {
        fn analyze(
            &self,
            provider: &str,
            chunk_id: &str,
            text: &str,
        ) -> Result<swe_gym::provider::ProviderAnswer, String> {
            match provider {
                "scan" => self.scan.analyze(provider, chunk_id, text),
                "deep" => self.deep.analyze(provider, chunk_id, text),
                other => Err(format!("unknown provider {other:?}")),
            }
        }
    }
    let both = ScanDeep { scan, deep };
    let recorder = RecordProvider::new(&both);

    for (chunk_id, text) in CHUNKS {
        let scan_answer = recorder
            .analyze("scan", chunk_id, text)
            .expect("JEV must answer or fail loudly");
        let deep_answer = recorder
            .analyze("deep", chunk_id, text)
            .expect("LLM must answer or fail loudly");
        let scan_tokens = swe_gym::provider::usage_tokens(&scan_answer.raw).unwrap_or((0, 0));
        let deep_tokens = swe_gym::provider::usage_tokens(&deep_answer.raw).unwrap_or((0, 0));
        println!(
            "{chunk_id}: scan {:<6} {:>5} {:>4} ms {}+{}  |  deep {:<6} {:>5} {:>4} ms {}+{}",
            scan_answer.choice,
            scan_answer.score_bp,
            scan_answer.latency_ms,
            scan_tokens.0,
            scan_tokens.1,
            deep_answer.choice,
            deep_answer.score_bp,
            deep_answer.latency_ms,
            deep_tokens.0,
            deep_tokens.1,
        );
    }

    let source = format!(
        "live JEV capture epoch-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .unwrap_or(0),
    );
    let fixture = recorder.to_fixture_with(&source, QUESTION);
    std::fs::write("benchmarks/jev_fixture_v1.json", fixture).expect("fixture must be writable");
    println!(
        "skrev benchmarks/jev_fixture_v1.json ({} anrop)",
        CHUNKS.len() * 2
    );
}
