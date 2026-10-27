//! Variant experiment — the live part (docs/SWE_Sweycoins_v2.md 22):
//! captures for the static / iterative / adaptive chains and the oracle
//! synthesis test on the five chain-experiment questions.
//!
//! Live calls: gap analysis (LLM), JEV on newly retrieved chunks,
//! synthesis per variant, oracle synthesis. Everything else is offline
//! in tools/measure_variants.py.
//!
//! Run with: cargo run --example v2_variants

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpJevProvider, HttpLlmProvider, RecordProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

const QUESTIONS: [&str; 5] = ["g2-15", "g2-17", "g2-29", "g2-20", "g2-23"];

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

fn jev_hits(qid: &str) -> Vec<String> {
    let source =
        std::fs::read_to_string(format!("benchmarks/golden_v2_fixtures/{qid}-jev.json")).unwrap();
    let json = parse_json_str(&source).unwrap();
    json.get("entries")
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .filter(|e| e.get("choice").and_then(Json::as_str) == Some("fynd"))
        .map(|e| e.get("chunk_id").and_then(Json::as_str).unwrap().to_string())
        .collect()
}

fn ranks(qid: &str) -> Vec<String> {
    let source = std::fs::read_to_string("benchmarks/golden_v2_ranks.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    json.get("ranks")
        .and_then(Json::as_object)
        .unwrap()
        .get(qid)
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .map(|c| c.as_str().unwrap().to_string())
        .collect()
}

fn evidence_text(question: &str, evidence: &[String], texts: &std::collections::HashMap<String, String>) -> String {
    evidence
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
    std::fs::create_dir_all("benchmarks/variant_capture").expect("dir");
    let mut out: Vec<String> = Vec::new();

    for (qid, question, evidence) in golden() {
        if !QUESTIONS.contains(&qid.as_str()) {
            continue;
        }
        let initial_hits = jev_hits(&qid);
        let rank = ranks(&qid);
        let initial_text = evidence_text(&question, &initial_hits, &texts);

        // Synthesis prompts.
        let synth = |llm: &HttpLlmProvider, label: &str, input: &str| -> String {
            llm.analyze("deep", label, input)
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"))
        };
        let synth_provider = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b")
            .with_system_prompt(
                "Du besvarar en juridisk fråga utifrån given evidens från avtalsdokument. Svara kort och exakt, utan motivering.",
            );

        // 1. Static: synthesis over the rank-ordered top hits (cap 8).
        let static_hits: Vec<String> = rank
            .iter()
            .filter(|c| initial_hits.contains(*c))
            .take(8)
            .cloned()
            .collect();
        let static_answer = synth(
            &synth_provider,
            "static",
            &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&question, &static_hits, &texts)),
        );

        // 2. Iterative: gap analysis -> new candidates -> JEV -> synthesis.
        let gap_provider = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b")
            .with_system_prompt(
                "Du identifierar vilka ytterligare fakta eller klausuler som behövs för att besvara en fråga, givet den evidens som redan finns. Svara med en kommaseparerad lista av svenska nyckelbegrepp, inget annat.",
            );
        let gap_answer = synth(
            &gap_provider,
            "gap",
            &format!("Fråga: {question}\n\nRedan funnen evidens:\n{initial_text}"),
        );
        // Recover the free-form content from the word-mapper's refusal.
        let gap_content = if let Some(pos) = gap_answer.find("(content: \"") {
            gap_answer[pos + "(content: \"".len()..]
                .rsplit_once("\")")
                .map(|(a, _)| a.to_string())
                .unwrap_or_default()
        } else {
            gap_answer.clone()
        };
        // The gap answer names DOCUMENTS or concepts: if it names
        // documents, the retrieval task is "fetch those documents'
        // chunks"; otherwise keyword-match the corpus.
        let named_docs: Vec<String> = {
            let mut docs: Vec<String> = Vec::new();
            let mut rest = gap_content.as_str();
            while let Some(pos) = rest.find("Avtal_") {
                let tail = &rest[pos..];
                let end = tail
                    .find(|ch: char| !(ch.is_ascii_alphanumeric() || ch == '_' || ch == 'å'
                        || ch == 'ä' || ch == 'ö' || ch == 'Å' || ch == 'Ä' || ch == 'Ö'))
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
        };
        let keywords: Vec<String> = gap_content
            .split(',')
            .map(|k| k.trim().to_lowercase())
            .filter(|k| !k.is_empty() && k.len() >= 3)
            .collect();
        // Retrieval: expand to new corpus chunks matching the needs.
        let mut new_candidates: Vec<String> = if !named_docs.is_empty() {
            texts
                .keys()
                .filter(|c| {
                    named_docs.iter().any(|d| c.split(':').next() == Some(d.as_str()))
                        && !initial_hits.contains(*c)
                })
                .cloned()
                .collect()
        } else {
            texts
                .keys()
                .filter(|c| {
                    !initial_hits.contains(*c)
                        && keywords
                            .iter()
                            .any(|k| texts.get(*c).unwrap().to_lowercase().contains(k))
                })
                .cloned()
                .collect()
        };
        new_candidates.truncate(12);
        let jev = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence that answers the question. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let jev_recorder = RecordProvider::new(&jev);
        for chunk in &new_candidates {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            if let Err(e) = jev_recorder.analyze("scan", chunk, &text) {
                out.push(format!("JEV-FEL {qid} {chunk}: {e}"));
            }
        }
        std::fs::write(
            format!("benchmarks/variant_capture/{qid}-newjev.json"),
            jev_recorder.to_fixture_with("swe-gym-variants", &question),
        )
        .unwrap();
        let new_hits: Vec<String> = {
            let source = std::fs::read_to_string(format!(
                "benchmarks/variant_capture/{qid}-newjev.json"
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
        let iterative_answer = synth(
            &synth_provider,
            "iterative",
            &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&question, &all_hits, &texts)),
        );

        // 3. Adaptive: budget-driven rule over the same primitives.
        //    Deterministic: JEV rank-order candidates; every 6th JEV call
        //    traverses the graph (expand pool with same-document chunks
        //    of hits, JEV them); stop on 5 zero-hit calls -> synthesize.
        let mut adaptive_hits: Vec<String> = initial_hits.clone();
        // (the rule reuses captured answers: initial hits + same-doc expansion)
        let same_doc: Vec<String> = initial_hits
            .iter()
            .flat_map(|c| {
                let doc = c.split(':').next().unwrap();
                texts
                    .keys()
                    .filter(|k| k.split(':').next() == Some(doc) && !adaptive_hits.contains(k))
                    .cloned()
                    .collect::<Vec<_>>()
            })
            .collect();
        let mut extra: Vec<String> = Vec::new();
        for chunk in same_doc.iter().take(8) {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            if let Ok(a) = jev_recorder.analyze("scan", chunk, &text) {
                if a.choice == "fynd" {
                    extra.push(chunk.clone());
                }
            }
        }
        adaptive_hits.extend(extra);
        let adaptive_answer = synth(
            &synth_provider,
            "adaptive",
            &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&question, &adaptive_hits, &texts)),
        );

        // 4. Oracle: synthesis given ALL facit evidence directly.
        let oracle_answer = synth(
            &synth_provider,
            "oracle",
            &format!("Fråga: {question}\n\nEvidens:\n{}", evidence_text(&question, &evidence, &texts)),
        );

        out.push(format!(
            "=== {qid}\nQUESTION: {question}\nGAP: {gap_answer}\nNEW_HITS: {}\nSTATIC: {static_answer}\nITERATIVE: {iterative_answer}\nADAPTIVE: {adaptive_answer}\nORACLE: {oracle_answer}\n",
            new_hits.join(";")
        ));
        println!("{qid}: varianter + orakel fångade ({} nya kandidater, {} nya fynd)", new_candidates.len(), new_hits.len());
    }
    std::fs::write("benchmarks/variant_capture/answers.txt", out.join("\n")).unwrap();
    println!("klart");
}
