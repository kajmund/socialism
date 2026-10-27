//! Dependency-case measurement — live part (docs/SWE_Sweycoins_v2.md 23):
//! the iterative chain over the 12 controlled dependency cases.
//! Per case: initial JEV+LLM over candidates, static synthesis, categorized
//! gap analysis, retrieval of the identified needs, JEV on the new
//! candidates, iterative synthesis. Hypothesis signals are computed
//! offline in tools/measure_dependencies.py.
//!
//! Run with: cargo run --example v2_dependencies

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpJevProvider, HttpLlmProvider, RecordProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

fn cases() -> Vec<(String, String, Vec<String>)> {
    let source = std::fs::read_to_string("benchmarks/golden_v3.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    json.get("questions")
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .map(|q| {
            (
                q.get("id").and_then(Json::as_str).unwrap().to_string(),
                q.get("question").and_then(Json::as_str).unwrap().to_string(),
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

fn doc_names(question: &str) -> Vec<String> {
    let mut docs = Vec::new();
    let mut rest = question;
    while let Some(pos) = rest.find("Avtal_") {
        let tail = &rest[pos..];
        let end = tail
            .find(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_'))
            .unwrap_or(tail.len());
        let name = &tail[..end];
        if name.starts_with("Avtal_") && name.matches('_').count() >= 2 {
            docs.push(name.to_string());
        }
        rest = &tail[end..];
    }
    docs.sort();
    docs.dedup();
    docs
}

fn evidence_text(chunks: &[String], texts: &std::collections::HashMap<String, String>) -> String {
    chunks
        .iter()
        .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn main() {
    let jev_key = resolve_secret("TYPESAFE_API_KEY", "../../backend/.env")
        .expect("TYPESAFE_API_KEY saknas");
    let jev_base = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let jev_model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let llm_key = resolve_secret("CEREBRAS_API_KEY", "../../backend/.env")
        .expect("CEREBRAS_API_KEY saknas");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());

    let texts = bench_texts();
    std::fs::create_dir_all("benchmarks/dependency_capture").expect("dir");
    let mut out: Vec<String> = Vec::new();

    let synth = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du besvarar en juridisk fråga utifrån given evidens från avtalsdokument. Svara kort och exakt, utan motivering.",
    );
    let cat_gap = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du identifierar ytterligare informationsbehov givet redan funnen evidens. Klassificera varje behov som REQUIRED (nödvändig för slutsatsen), SUPPORTING (stärker eller förklarar) eller EXPLORATORY (okänd betydelse). Svara som 'behov: kategori' per rad. Om inget ytterligare behövs, svara INGET.",
    );

    for (qid, question, evidence) in cases() {
        let docs = doc_names(&question);
        // Candidates: facit evidence + distractors from the named docs and beyond.
        let mut candidates: Vec<String> = evidence.clone();
        for (c, _t) in texts.iter() {
            if candidates.len() >= 16 {
                break;
            }
            if !candidates.contains(c) {
                let doc = c.split(':').next().unwrap();
                if docs.iter().any(|d| d == doc) || candidates.len() >= 8 {
                    candidates.push(c.clone());
                }
            }
        }

        let jev = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence that answers the question. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let jev_recorder = RecordProvider::new(&jev);
        let llm = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
            &format!("Du klassificerar avtalstext. Fråga: {question} Svara med exakt ett ord: JA, NEJ eller OSÄKER."),
        );
        let llm_recorder = RecordProvider::new(&llm);
        for chunk in &candidates {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            let _ = jev_recorder.analyze("scan", chunk, &text);
            let _ = llm_recorder.analyze("deep", chunk, &text);
        }
        std::fs::write(
            format!("benchmarks/dependency_capture/{qid}-jev.json"),
            jev_recorder.to_fixture_with("swe-gym-deps", &question),
        )
        .unwrap();
        std::fs::write(
            format!("benchmarks/dependency_capture/{qid}-llm.json"),
            llm_recorder.to_fixture_with("swe-gym-deps", &question),
        )
        .unwrap();

        let initial_hits: Vec<String> = {
            let source = std::fs::read_to_string(format!(
                "benchmarks/dependency_capture/{qid}-jev.json"
            ))
            .unwrap();
            let json = parse_json_str(&source).unwrap();
            json.get("entries")
                .and_then(Json::as_array)
                .unwrap()
                .iter()
                .filter(|e| e.get("choice").and_then(Json::as_str) == Some("fynd"))
                .map(|e| e.get("chunk_id").and_then(Json::as_str).unwrap().to_string())
                .collect()
        };
        let static_answer = synth
            .analyze("deep", "static", &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&initial_hits, &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));
        let gap = cat_gap
            .analyze("deep", "cat-gap", &format!("Fråga: {question}\n\nRedan funnen evidens:\n{}", evidence_text(&initial_hits, &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Retrieval: fetch chunks from documents named by the gap (the
        // needs), then JEV them.
        let gap_docs = doc_names(&gap);
        let mut new_candidates: Vec<String> = texts
            .keys()
            .filter(|c| {
                let doc = c.split(':').next().unwrap();
                gap_docs.iter().any(|d| d == doc) && !initial_hits.contains(*c)
            })
            .cloned()
            .collect();
        new_candidates.truncate(12);
        let jev2 = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence that answers the question. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let jev2_recorder = RecordProvider::new(&jev2);
        for chunk in &new_candidates {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            let _ = jev2_recorder.analyze("scan", chunk, &text);
        }
        std::fs::write(
            format!("benchmarks/dependency_capture/{qid}-newjev.json"),
            jev2_recorder.to_fixture_with("swe-gym-deps", &question),
        )
        .unwrap();
        let new_hits: Vec<String> = {
            let source = std::fs::read_to_string(format!(
                "benchmarks/dependency_capture/{qid}-newjev.json"
            ))
            .unwrap();
            let json = parse_json_str(&source).unwrap();
            json.get("entries")
                .and_then(Json::as_array)
                .unwrap()
                .iter()
                .filter(|e| e.get("choice").and_then(Json::as_str) == Some("fynd"))
                .map(|e| e.get("chunk_id").and_then(Json::as_str).unwrap().to_string())
                .collect()
        };
        let mut all_hits = initial_hits.clone();
        all_hits.extend(new_hits.iter().cloned());
        let iterative_answer = synth
            .analyze("deep", "iterative", &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&all_hits, &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        out.push(format!(
            "=== {qid}\nQUESTION: {question}\nSTATIC: {static_answer}\nGAP: {gap}\nNEW_HITS: {}\nITERATIVE: {iterative_answer}\n",
            new_hits.join(";")
        ));
        println!("{qid}: {} kandidater, {} initiala fynd, {} nya fynd", candidates.len(), initial_hits.len(), new_hits.len());
    }
    std::fs::write("benchmarks/dependency_capture/answers.txt", out.join("\n")).unwrap();
    println!("klart");
}
