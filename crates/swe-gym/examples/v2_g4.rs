//! The g4 breaking-set run (docs/SWE_Sweycoins_v2.md 32): live capture
//! of the six cases — clarified-evidence JEV over the candidates and the
//! gated SYNTHESIZE_RISK synthesis call. Everything else (the selective
//! rule, the operation contracts, the control flow, the economy) is
//! offline in tools/measure_g4.py. No rules are adjusted on outcomes.
//!
//! Run with: cargo run --example v2_g4

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpJevProvider, HttpLlmProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

fn cases() -> Vec<(String, String, Vec<String>)> {
    let source = std::fs::read_to_string("benchmarks/golden_v4.json").unwrap();
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
    std::fs::create_dir_all("benchmarks/g4_capture").expect("dir");
    let mut out: Vec<String> = Vec::new();
    let mut total_jv = 0usize;
    let mut total_llm = 0usize;

    for (qid, question, evidence) in cases() {
        // Candidates: evidence + deterministic distractors from the same
        // documents (bounded).
        let doc = evidence
            .first()
            .map(|c| c.split(':').next().unwrap().to_string())
            .unwrap_or_default();
        let mut candidates: Vec<String> = evidence.clone();
        for (c, _t) in texts.iter() {
            if candidates.len() >= 8 {
                break;
            }
            if c.split(':').next() == Some(doc.as_str()) && !candidates.contains(c) {
                candidates.push(c.clone());
            }
        }

        let clarified_prompt = format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence RELEVANT to answering the question. Olika formuleringar är ekvivalenta: 'sägs upp senast X månader före utgång' betyder 'har X månaders uppsägningstid'. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN.");
        let jev = HttpJevProvider::new(&jev_key, &jev_base, &jev_model)
            .with_instructions(&clarified_prompt);
        let mut verdicts: Vec<String> = Vec::new();
        for chunk in &candidates {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            let v = jev
                .analyze("scan", "g4", &text)
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            total_jv += 1;
            verdicts.push(format!("{chunk}={v}"));
        }

        // SYNTHESIZE_RISK: the gated reasoning call (the gate is applied
        // offline; the answer is captured for the rubric).
        let mut risk_answer = String::from("-");
        if qid == "g4-05" {
            let synth = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b")
                .with_system_prompt(
                    "Du besvarar en juridisk fråga utifrån given verifierad evidens. Använd alla givna fakta, skilj avtalsvillkor från juridiska slutsatser, nämn undantag, hänvisa till evidensen och avstå från slutsatser underlaget inte stödjer. Svara kort.",
                );
            let ev = evidence
                .iter()
                .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
                .collect::<Vec<_>>()
                .join("\n\n");
            risk_answer = synth
                .analyze(
                    "deep",
                    "risk",
                    &format!("Fråga: {question}\n\nVerifierad evidens:\n{ev}"),
                )
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            total_llm += 1;
        }

        out.push(format!(
            "=== {qid}\nQUESTION: {question}\nVERDICTS: {}\nRISK: {risk_answer}\n",
            verdicts.join(";")
        ));
        println!(
            "{qid}: {} kandidater, {} JEV totalt",
            candidates.len(),
            total_jv
        );
    }
    std::fs::write("benchmarks/g4_capture/answers.txt", out.join("\n")).unwrap();
    println!("klart: {total_jv} JEV-anrop, {total_llm} LLM-anrop");
}
