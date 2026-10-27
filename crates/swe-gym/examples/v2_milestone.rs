//! The sharpened milestone experiment (docs/SWE_Sweycoins_v2.md 24):
//! same rank-based initial candidates for all chains, structured needs
//! (need / document / importance / status / evidence), need-targeted
//! retrieval, and the plain K-expansion arm as the economic baseline.
//! Facit never enters candidate generation or gap decisions — only
//! evaluation.
//!
//! Run with: cargo run --example v2_milestone

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpJevProvider, HttpLlmProvider, RecordProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

const K: usize = 8;
const K_DELTA: usize = 8;
const NEED_BUDGET: usize = 6; // max JEV calls per need

fn cases() -> Vec<(String, String)> {
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
            )
        })
        .collect()
}

fn ranks() -> std::collections::HashMap<String, Vec<String>> {
    let source = std::fs::read_to_string("benchmarks/golden_v3_ranks.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    let mut out = std::collections::HashMap::new();
    let r = json.get("ranks").and_then(Json::as_object).unwrap();
    for (qid, list) in r {
        out.insert(
            qid.clone(),
            list.as_array()
                .unwrap()
                .iter()
                .map(|c| c.as_str().unwrap().to_string())
                .collect(),
        );
    }
    out
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

fn evidence_text(chunks: &[String], texts: &std::collections::HashMap<String, String>) -> String {
    chunks
        .iter()
        .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn hits_of(qid: &str, which: &str) -> Vec<String> {
    let path = format!("benchmarks/milestone_capture/{qid}-{which}.json");
    let source = std::fs::read_to_string(&path).unwrap_or_default();
    if source.is_empty() {
        return Vec::new();
    }
    let json = parse_json_str(&source).unwrap();
    json.get("entries")
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .filter(|e| e.get("choice").and_then(Json::as_str) == Some("fynd"))
        .map(|e| e.get("chunk_id").and_then(Json::as_str).unwrap().to_string())
        .collect()
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
    let rank = ranks();
    std::fs::create_dir_all("benchmarks/milestone_capture").expect("dir");
    let mut out: Vec<String> = Vec::new();

    let synth = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du besvarar en juridisk fråga utifrån given evidens från avtalsdokument. Svara kort och exakt, utan motivering.",
    );
    let gap = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du identifierar informationsbehov givet redan funnen evidens. Svara med ENBART en JSON-lista av objekt med fälten need (kort behov), document (Avtal_XX eller null), importance (REQUIRED, SUPPORTING eller EXPLORATORY). Om inget ytterligare behövs, svara [].",
    );

    for (qid, question) in cases() {
        let pool = rank.get(&qid).expect("rank exists");
        let top_k: Vec<String> = pool.iter().take(K).cloned().collect();
        let top_kd: Vec<String> = pool.iter().take(K + K_DELTA).cloned().collect();

        // Capture JEV+LLM once over top-(K+delta) — covers all arms.
        // Resume-safe: reuse the frozen initial capture when it exists.
        let initial_path = format!("benchmarks/milestone_capture/{qid}-initial.json");
        // Pool changed: recapture the initial answers unconditionally.
        let jev = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence RELEVANT to answering the question — a text can be necessary evidence without answering the question alone. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let jev_rec = RecordProvider::new(&jev);
        let llm = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
            &format!("Du klassificerar avtalstext. Fråga: {question} Svara med exakt ett ord: JA, NEJ eller OSÄKER."),
        );
        let llm_rec = RecordProvider::new(&llm);
        for chunk in &top_kd {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            let _ = jev_rec.analyze("scan", chunk, &text);
            let _ = llm_rec.analyze("deep", chunk, &text);
        }
        std::fs::write(&initial_path, jev_rec.to_fixture_with("swe-gym-milestone", &question))
            .unwrap();


        let initial_hits: Vec<String> = {
            let source =
                std::fs::read_to_string(format!("benchmarks/milestone_capture/{qid}-initial.json"))
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
        let hits_in = |pool_subset: &[String]| -> Vec<String> {
            initial_hits
                .iter()
                .filter(|c| pool_subset.contains(c))
                .cloned()
                .collect()
        };

        // Static: top-K hits.
        let static_answer = synth
            .analyze("deep", "static", &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&hits_in(&top_k), &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));
        // K-expansion: top-(K+delta) hits.
        let kexp_answer = synth
            .analyze("deep", "kexp", &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&hits_in(&top_kd), &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Iterative: structured gap -> need-targeted retrieval.
        let gap_answer = gap
            .analyze("deep", "gap", &format!("Fråga: {question}\n\nRedan funnen evidens:\n{}", evidence_text(&hits_in(&top_k), &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Parse the needs (JSON or FEL-recovered).
        let gap_content = if let Some(pos) = gap_answer.find("(content: \"") {
            gap_answer[pos + "(content: \"".len()..]
                .rsplit_once("\")")
                .map(|(a, _)| a.to_string())
                .unwrap_or_default()
        } else {
            gap_answer.clone()
        };
        // The model emits JSON with literal escape sequences outside
        // strings; normalize them before parsing (the needs' text has no
        // embedded quotes or newlines).
        let gap_clean = gap_content.replace("\\n", " ").replace("\\\"", "\"");
        let needs_json = parse_json_str(&gap_clean);
        let mut needs: Vec<(String, String, String)> = Vec::new();
        if let Ok(json) = needs_json {
            if let Some(list) = json.as_array() {
                for item in list {
                    let need = item.get("need").and_then(Json::as_str).unwrap_or("").to_string();
                    let doc = item
                        .get("document")
                        .and_then(Json::as_str)
                        .unwrap_or("")
                        .to_string();
                    let imp = item
                        .get("importance")
                        .and_then(Json::as_str)
                        .unwrap_or("EXPLORATORY")
                        .to_string();
                    if !need.is_empty() {
                        needs.push((need, doc, imp));
                    }
                }
            }
        }

        let mut need_lines = Vec::new();
        let mut all_hits = hits_in(&top_k);
        let jev2 = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence RELEVANT to answering the question — a text can be necessary evidence without answering the question alone. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let jev2_rec = RecordProvider::new(&jev2);
        for (need, doc, imp) in &needs {
            // Rank-ordered retrieval: the highest-ranked unverified
            // chunks of the need's document first — the honest retrieval
            // behavior, bounded by the need budget.
            let mut targets: Vec<String> = if !doc.is_empty() && doc != "null" {
                pool.iter()
                    .filter(|c| c.split(':').next() == Some(doc.as_str()) && !top_k.contains(*c))
                    .cloned()
                    .collect()
            } else {
                pool.iter()
                    .filter(|c| {
                        !top_k.contains(*c)
                            && texts
                                .get(*c)
                                .unwrap()
                                .to_lowercase()
                                .contains(&need.to_lowercase())
                    })
                    .cloned()
                    .collect()
            };
            targets.truncate(NEED_BUDGET);
            let mut resolved = Vec::new();
            for chunk in &targets {
                let text = texts.get(chunk).cloned().unwrap_or_default();
                if let Ok(a) = jev2_rec.analyze("scan", chunk, &text) {
                    if a.choice == "fynd" {
                        resolved.push(chunk.clone());
                        all_hits.push(chunk.clone());
                    }
                }
            }
            let status = if resolved.is_empty() { "UNRESOLVED" } else { "RESOLVED" };
            need_lines.push(format!("{need}|{doc}|{imp}|{status}|{}", resolved.join(";")));
        }
        std::fs::write(
            format!("benchmarks/milestone_capture/{qid}-needjev.json"),
            jev2_rec.to_fixture_with("swe-gym-milestone", &question),
        )
        .unwrap();

        let iterative_answer = synth
            .analyze("deep", "iterative", &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&all_hits, &texts)))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        out.push(format!(
            "=== {qid}\nQUESTION: {question}\nSTATIC: {static_answer}\nKEXP: {kexp_answer}\nGAP: {gap_content}\nNEEDS: {}\nITERATIVE: {iterative_answer}\n",
            need_lines.join(" || ")
        ));
        println!("{qid}: top-{K} fynd {}, behov {}, iterativa fynd {}", hits_in(&top_k).len(), needs.len(), all_hits.len());
    }
    std::fs::write("benchmarks/milestone_capture/answers.txt", out.join("\n")).unwrap();
    println!("klart");
}
