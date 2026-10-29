//! Three-state execution model + four synthesis variants (docs 25):
//! INVESTIGATING / READY_TO_SYNTHESIZE / INSUFFICIENT_EVIDENCE as
//! deterministic control logic. A REQUIRED need is RESOLVED only with a
//! concrete, JEV-verified TextUnit in the right document whose text
//! contains the asked-for fact (keyword); contradictions are flagged in
//! the offline analysis. Synthesis is invoked only when the gate says
//! READY — the model never decides whether to wait.
//!
//! Run with: cargo run --example v2_states

use swe_gym::provider::{
    resolve_secret, HttpJevProvider, HttpLlmProvider, RecordProvider, ResearchProvider,
};
use swe_native::{parse_json_str, Json};

const K: usize = 8;
const NEED_BATCH: usize = 6;
const NEED_JV_CAP: usize = 14; // JEV calls per need
const GAP_CAP: usize = 3; // gap-analysis calls per case
const GLOBAL_JV_CAP: usize = 42; // JEV calls per case beyond initial

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
                q.get("question")
                    .and_then(Json::as_str)
                    .unwrap()
                    .to_string(),
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

fn evidence_text(chunks: &[String], texts: &std::collections::HashMap<String, String>) -> String {
    chunks
        .iter()
        .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn initial_hits(qid: &str) -> Vec<String> {
    let path = format!("benchmarks/milestone_capture/{qid}-initial.json");
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
        .map(|e| {
            e.get("chunk_id")
                .and_then(Json::as_str)
                .unwrap()
                .to_string()
        })
        .collect()
}

fn main() {
    let jev_key =
        resolve_secret("TYPESAFE_API_KEY", "../../backend/.env").expect("TYPESAFE_API_KEY saknas");
    let jev_base = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let jev_model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let llm_key =
        resolve_secret("CEREBRAS_API_KEY", "../../backend/.env").expect("CEREBRAS_API_KEY saknas");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());

    let texts = bench_texts();
    let rank = ranks();
    std::fs::create_dir_all("benchmarks/states_capture").expect("dir");
    let mut out: Vec<String> = Vec::new();

    let synth = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du besvarar en juridisk fråga utifrån given evidens från avtalsdokument. Svara kort och exakt, utan motivering.",
    );
    let matrix = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du strukturerar avtalsevidens som en matris. För varje dokument: rader med 'Dokument | Villkor | Värde'. Endast matrisen, ingen slutsats.",
    );
    let gap = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
        "Du identifierar informationsbehov givet redan funnen evidens. Svara med ENBART en JSON-lista av objekt med fälten need (kort behov), document (Avtal_XX eller null), importance (REQUIRED, SUPPORTING eller EXPLORATORY). Om inget ytterligare behövs, svara [].",
    );

    for (qid, question) in cases() {
        let pool = rank.get(&qid).expect("rank exists");
        let top_k: Vec<String> = pool.iter().take(K).cloned().collect();
        let mut hits = initial_hits(&qid);
        let mut verified: Vec<String> = Vec::new(); // chunks verified beyond initial
        let mut gap_calls = 0usize;
        let mut jv_spent = 0usize;

        // The state machine: INVESTIGATING until all REQUIRED needs are
        // resolved or the budget/sources give out.
        let mut needs: Vec<(String, String, String)> = Vec::new();
        let mut need_evidence: Vec<Vec<String>> = Vec::new();
        let mut state = "INVESTIGATING";

        let jev = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence RELEVANT to answering the question — a text can be necessary evidence without answering the question alone. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let mut jev_rec = RecordProvider::new(&jev);

        for _ in 0..GAP_CAP {
            if state != "INVESTIGATING" {
                break;
            }
            let gap_answer = gap
                .analyze(
                    "deep",
                    "gap",
                    &format!(
                        "Fråga: {question}\n\nRedan funnen evidens:\n{}",
                        evidence_text(&hits, &texts)
                    ),
                )
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            gap_calls += 1;
            let gap_content = if let Some(pos) = gap_answer.find("(content: \"") {
                gap_answer[pos + "(content: \"".len()..]
                    .rsplit_once("\")")
                    .map(|(a, _)| a.to_string())
                    .unwrap_or_default()
            } else {
                gap_answer.clone()
            };
            let gap_clean = gap_content.replace("\\n", " ").replace("\\\"", "\"");
            needs = Vec::new();
            if let Ok(json) = parse_json_str(&gap_clean) {
                if let Some(list) = json.as_array() {
                    for item in list {
                        let n = item
                            .get("need")
                            .and_then(Json::as_str)
                            .unwrap_or("")
                            .to_string();
                        let d = item
                            .get("document")
                            .and_then(Json::as_str)
                            .unwrap_or("")
                            .to_string();
                        let i = item
                            .get("importance")
                            .and_then(Json::as_str)
                            .unwrap_or("EXPLORATORY")
                            .to_string();
                        if !n.is_empty() {
                            needs.push((n, d, i));
                        }
                    }
                }
            }
            // A REQUIRED need may already be satisfied by the existing
            // hits: then it is RESOLVED without further calls.
            need_evidence = (0..needs.len())
                .map(|ix| {
                    let (n, d, i) = &needs[ix];
                    if i != "REQUIRED" {
                        return Vec::new();
                    }
                    let concept = n.split(" för ").next().unwrap_or(n).trim().to_lowercase();
                    hits.iter()
                        .filter(|c| {
                            (d.is_empty() || d == "null" || c.split(':').next() == Some(d.as_str()))
                                && {
                                    let text =
                                        texts.get(*c).cloned().unwrap_or_default().to_lowercase();
                                    text.contains(&concept)
                                        || (concept.contains("upps") && text.contains("upps"))
                                }
                        })
                        .cloned()
                        .collect()
                })
                .collect();
            if needs.iter().all(|(_, _, i)| i != "REQUIRED") {
                break; // no REQUIRED needs -> the gate's verdict below
            }
            // Resolve REQUIRED needs in order: fetch the next batch of
            // the need's document chunks in rank order and verify.
            let required: Vec<usize> = (0..needs.len())
                .filter(|&ix| needs[ix].2 == "REQUIRED")
                .collect();
            let mut resolved_this_round = Vec::new();
            for &ix in &required {
                let (n, d, _) = &needs[ix];
                let existing = need_evidence.get(ix).cloned().unwrap_or_default();
                let mut found = existing;
                if found.is_empty() {
                    let concept = n.split(" för ").next().unwrap_or(n).trim().to_lowercase();
                    let mut targets: Vec<String> = if !d.is_empty() && d != "null" {
                        pool.iter()
                            .filter(|c| {
                                c.split(':').next() == Some(d.as_str())
                                    && !top_k.contains(*c)
                                    && !verified.contains(*c)
                            })
                            .cloned()
                            .collect()
                    } else {
                        pool.iter()
                            .filter(|c| {
                                !top_k.contains(*c)
                                    && !verified.contains(*c)
                                    && texts
                                        .get(*c)
                                        .unwrap()
                                        .to_lowercase()
                                        .contains(&n.to_lowercase())
                            })
                            .cloned()
                            .collect()
                    };
                    targets.truncate(NEED_BATCH);
                    let mut batch_hits = Vec::new();
                    for chunk in targets.iter().take(NEED_BATCH) {
                        if jv_spent >= GLOBAL_JV_CAP || batch_hits.len() >= NEED_JV_CAP {
                            break;
                        }
                        let text = texts.get(chunk).cloned().unwrap_or_default();
                        jv_spent += 1;
                        if let Ok(a) = jev_rec.analyze("scan", chunk, &text) {
                            verified.push(chunk.clone());
                            // RESOLVED: verified fynd in the right document
                            // whose text contains the asked-for fact.
                            let text_l = text.to_lowercase();
                            if a.choice == "fynd"
                                && (d.is_empty()
                                    || d == "null"
                                    || chunk.split(':').next() == Some(d.as_str()))
                                && (text_l.contains(&concept)
                                    || (concept.contains("upps") && text_l.contains("upps")))
                            {
                                batch_hits.push(chunk.clone());
                                hits.push(chunk.clone());
                            }
                        }
                    }
                    found = batch_hits;
                    if found.is_empty() {
                        // widen once more for this need
                        let mut more: Vec<String> = if !d.is_empty() && d != "null" {
                            pool.iter()
                                .filter(|c| {
                                    c.split(':').next() == Some(d.as_str())
                                        && !top_k.contains(*c)
                                        && !verified.contains(*c)
                                })
                                .cloned()
                                .collect()
                        } else {
                            Vec::new()
                        };
                        more.truncate(NEED_BATCH);
                        for chunk in &more {
                            if jv_spent >= GLOBAL_JV_CAP {
                                break;
                            }
                            let text = texts.get(chunk).cloned().unwrap_or_default();
                            jv_spent += 1;
                            if let Ok(a) = jev_rec.analyze("scan", chunk, &text) {
                                verified.push(chunk.clone());
                                let text_l = text.to_lowercase();
                                if a.choice == "fynd"
                                    && (d.is_empty()
                                        || d == "null"
                                        || chunk.split(':').next() == Some(d.as_str()))
                                    && (text_l.contains(&concept)
                                        || (concept.contains("upps") && text_l.contains("upps")))
                                {
                                    found.push(chunk.clone());
                                    hits.push(chunk.clone());
                                }
                            }
                        }
                    }
                    if ix >= need_evidence.len() {
                        need_evidence.resize(ix + 1, Vec::new());
                    }
                    need_evidence[ix] = found.clone();
                }
                if !found.is_empty() {
                    resolved_this_round.push(ix);
                }
            }
            if resolved_this_round.len() == required.len() || jv_spent >= GLOBAL_JV_CAP {
                break;
            }
        }

        let required_total = needs.iter().filter(|(_, _, i)| i == "REQUIRED").count();
        let required_resolved = (0..needs.len())
            .filter(|ix| {
                needs[*ix].2 == "REQUIRED"
                    && !need_evidence
                        .get(*ix)
                        .cloned()
                        .unwrap_or_default()
                        .is_empty()
            })
            .count();
        if required_total > 0 && required_resolved == required_total {
            state = "READY_TO_SYNTHESIZE";
        } else if required_total > 0 {
            state = "INSUFFICIENT_EVIDENCE";
        } else {
            // no REQUIRED needs at all: synthesize only if we have hits
            state = if hits.is_empty() {
                "INSUFFICIENT_EVIDENCE"
            } else {
                "READY_TO_SYNTHESIZE"
            };
        }

        let mut gate_answer = String::from("-");
        let mut matrix_conclusion = String::from("-");
        if state == "READY_TO_SYNTHESIZE" {
            let ev = evidence_text(&hits, &texts);
            gate_answer = synth
                .analyze(
                    "deep",
                    "gate-synthesis",
                    &format!("Fråga: {question}\n\nEvidens:\n{ev}"),
                )
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            let m = matrix
                .analyze(
                    "deep",
                    "matrix",
                    &format!("Fråga: {question}\n\nEvidens:\n{ev}"),
                )
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            matrix_conclusion = synth
                .analyze(
                    "deep",
                    "matrix-conclusion",
                    &format!("Fråga: {question}\n\nStrukturerad evidensmatris:\n{m}"),
                )
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
        }

        std::fs::write(
            format!("benchmarks/states_capture/{qid}-needjev.json"),
            jev_rec.to_fixture_with("swe-gym-states", &question),
        )
        .unwrap();

        let need_lines: Vec<String> = needs
            .iter()
            .enumerate()
            .map(|(ix, (n, d, i))| {
                let ev = need_evidence.get(ix).cloned().unwrap_or_default();
                let status = if i == "REQUIRED" && ev.is_empty() {
                    "UNRESOLVED"
                } else {
                    "RESOLVED"
                };
                format!("{n}|{d}|{i}|{status}|{}", ev.join(";"))
            })
            .collect();
        out.push(format!(
            "=== {qid}\nQUESTION: {question}\nSTATE: {state}\nNEEDS: {}\nHITS: {}\nGATE_SYNTH: {gate_answer}\nMATRIX_CONCLUSION: {matrix_conclusion}\n",
            need_lines.join(" || "),
            hits.join(";")
        ));
        println!(
            "{qid}: {state}, behov {} ({} REQUIRED, {} lösta), {} JEV-anrop, {} gap-anrop",
            needs.len(),
            required_total,
            required_resolved,
            jv_spent,
            gap_calls
        );
    }
    std::fs::write("benchmarks/states_capture/answers.txt", out.join("\n")).unwrap();
    println!("klart");
}
