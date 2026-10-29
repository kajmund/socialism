//! Oracle decomposition + categorized gap analysis — live part
//! (docs/SWE_Sweycoins_v2.md 23). For the questions where direct oracle
//! synthesis failed (g2-15, g2-29, g2-23), capture the structured
//! evidence-matrix variant and the matrix+conclusion variant; and
//! re-run the gap analysis with the three-category need classification
//! (REQUIRED / SUPPORTING / EXPLORATORY).
//!
//! Run with: cargo run --example v2_oracle_decomp

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpLlmProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

fn golden() -> Vec<(String, String, Vec<String>)> {
    let source = std::fs::read_to_string("benchmarks/golden_v2.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    json.get("questions")
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .map(|q| {
            (
                q.get("id").and_then(Json::as_str).unwrap().to_string(),
                q.get("question")
                    .and_then(Json::as_str)
                    .unwrap()
                    .to_string(),
                q.get("evidence")
                    .and_then(Json::as_array)
                    .unwrap()
                    .iter()
                    .map(|e| e.as_str().unwrap().to_string())
                    .collect(),
            )
        })
        .collect()
}

fn bench_texts() -> std::collections::HashMap<String, String> {
    let bench = load_bench_file("benchmarks/bench_real_v2.json").expect("real bench");
    let mut texts = std::collections::HashMap::new();
    for q in &bench.questions {
        for (chunk, text) in &q.texts {
            texts.insert(chunk.clone(), text.clone());
        }
    }
    texts
}

fn jev_hits(qid: &str) -> Vec<String> {
    let source =
        std::fs::read_to_string(format!("benchmarks/golden_v2_fixtures/{qid}-jev.json")).unwrap();
    let json = parse_json_str(&source).unwrap();
    json.get("entries")
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .filter(|e| e.get("choice").and_then(Json::as_str) == Some("fynd"))
        .map(|e| {
            e.get("chunk_id")
                .and_then(Json::as_str)
                .unwrap()
                .to_string()
        })
        .collect()
}

fn evidence_text(chunks: &[String], texts: &std::collections::HashMap<String, String>) -> String {
    chunks
        .iter()
        .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn main() {
    let llm_key =
        resolve_secret("CEREBRAS_API_KEY", "../../backend/.env").expect("CEREBRAS_API_KEY saknas");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());
    let texts = bench_texts();
    std::fs::create_dir_all("benchmarks/oracle_decomp").expect("dir");
    let mut out: Vec<String> = Vec::new();

    let synth = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du besvarar en juridisk fråga utifrån given evidens från avtalsdokument. Svara kort och exakt, utan motivering.",
    );
    let matrix = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du strukturerar avtalsevidens som en matris. För varje dokument: rader med 'Dokument | Villkor | Betydelse för frågan'. Endast matrisen, ingen slutsats.",
    );
    let cat_gap = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du identifierar ytterligare informationsbehov givet redan funnen evidens. Klassificera varje behov som REQUIRED (nödvändig för slutsatsen), SUPPORTING (stärker eller förklarar) eller EXPLORATORY (okänd betydelse). Svara som 'behov: kategori' per rad.",
    );

    for (qid, question, evidence) in golden() {
        let initial_hits = jev_hits(&qid);
        let initial_text = evidence_text(&initial_hits, &texts);

        // Categorized gap analysis for all five chain questions.
        let gap = cat_gap
            .analyze(
                "deep",
                "cat-gap",
                &format!("Fråga: {question}\n\nRedan funnen evidens:\n{initial_text}"),
            )
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        out.push(format!("=== {qid}\nCATEGORIZED_GAP: {gap}\n"));

        if !["g2-15", "g2-29", "g2-23"].contains(&qid.as_str()) {
            println!("{qid}: kategoriserad gap fångad");
            continue;
        }
        // Oracle decomposition: matrix over ALL facit evidence.
        let full_text = evidence_text(&evidence, &texts);
        let m = matrix
            .analyze(
                "deep",
                "matrix",
                &format!("Fråga: {question}\n\nEvidens:\n{full_text}"),
            )
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));
        let m_concl = synth
            .analyze(
                "deep",
                "matrix-conclusion",
                &format!("Fråga: {question}\n\nStrukturerad evidensmatris:\n{m}"),
            )
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));
        out.push(format!("MATRIX: {m}\nMATRIX_CONCLUSION: {m_concl}\n"));
        println!("{qid}: matris + matrisslutsats fångade");
    }
    std::fs::write("benchmarks/oracle_decomp/answers.txt", out.join("\n")).unwrap();
    println!("klart");
}
