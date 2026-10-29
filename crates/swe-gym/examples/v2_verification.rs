//! Verification-signal experiment (docs/SWE_Sweycoins_v2.md 26): the
//! frozen test of the brittle signal that blocked g3-01. Five variants
//! over the same clauses: current prompt (baseline), clarified evidence
//! relevance (paraphrases are equivalent), clause context (document +
//! neighboring heading), repeated baseline (instability), and the
//! deterministic extractor (no model — computed offline).
//!
//! Run with: cargo run --example v2_verification

use swe_gym::provider::{resolve_secret, HttpJevProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

const QUESTION: &str = "Vilket av dessa dokument har längst uppsägningstid? (Avtal_17_Hyresavtal_lokal, Avtal_18_Hyresavtal_bostad, Avtal_20_Arrendeavtal_lagenhetsarrende)";

const CHUNKS: [&str; 6] = [
    // The three facit evidence chunks (all should be YES).
    "Avtal_17_Hyresavtal_lokal:9",
    "Avtal_18_Hyresavtal_bostad:5",
    "Avtal_20_Arrendeavtal_lagenhetsarrende:7",
    // Distractors (no notice-period content).
    "Avtal_17_Hyresavtal_lokal:1",
    "Avtal_18_Hyresavtal_bostad:2",
    "Avtal_20_Arrendeavtal_lagenhetsarrende:1",
];

fn bench_texts() -> std::collections::HashMap<String, String> {
    use swe_gym::bench::load_bench_file;
    let bench = load_bench_file("benchmarks/bench_real_v2.json").expect("real bench");
    let mut texts = std::collections::HashMap::new();
    for q in &bench.questions {
        for (chunk, text) in &q.texts {
            texts.insert(chunk.clone(), text.clone());
        }
    }
    texts
}

fn main() {
    let jev_key = resolve_secret("TYPESAFE_API_KEY", "../../backend/.env")
        .expect("TYPESAFE_API_KEY saknas");
    let jev_base = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let jev_model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let texts = bench_texts();

    let baseline_prompt = format!("{QUESTION} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence RELEVANT to answering the question — a text can be necessary evidence without answering the question alone. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN.");
    let clarified_prompt = format!("{baseline_prompt} Olika formuleringar är ekvivalenta: 'sägs upp senast X månader före utgång' betyder 'har X månaders uppsägningstid', och 'förlängs om det inte sägs upp' rör också uppsägningstiden.");

    let baseline = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(&baseline_prompt);
    let clarified = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(&clarified_prompt);

    let mut entries: Vec<String> = Vec::new();
    for chunk in CHUNKS {
        let text = texts.get(chunk).cloned().unwrap_or_default();
        let doc = chunk.split(':').next().unwrap();

        let base = baseline
            .analyze("scan", "verif-base", &text)
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));
        let clar = clarified
            .analyze("scan", "verif-clarified", &text)
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Context variant: document name + the chunk's heading line.
        let heading = text.lines().next().unwrap_or("").to_string();
        let context_text = format!("[Dokument: {doc}]\n[Klausulrubrik: {heading}]\n{text}");
        let ctx_provider = HttpJevProvider::new(&jev_key, &jev_base, &jev_model)
            .with_instructions(&baseline_prompt);
        let ctx = ctx_provider
            .analyze("scan", "verif-context", &context_text)
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Repeated baseline (3 runs) — instability check.
        let mut repeats = Vec::new();
        for i in 0..3 {
            let rep = HttpJevProvider::new(&jev_key, &jev_base, &jev_model)
                .with_instructions(&baseline_prompt);
            let r = rep
                .analyze("scan", "verif-repeat", &text)
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            repeats.push(format!("rep{}={r}", i + 1));
        }

        entries.push(format!(
            "{chunk}|{base}|{clar}|{ctx}|{}",
            repeats.join(";")
        ));
        println!("{chunk}: bas={base} klar={clar} kontext={ctx}");
    }
    std::fs::write("benchmarks/verification_signal.txt", entries.join("\n")).unwrap();
    println!("klart");
}
