//! Chain experiment — the live part (docs/SWE_Sweycoins_v2.md 21): the
//! synthesis calls for chains C (JEV -> LLM) and D (LLM -> JEV -> LLM) on
//! five selected cross-document / synthesis questions. Chains A and B need
//! no live calls (frozen fixtures + deterministic assembler); the full
//! comparison is offline in tools/measure_chains.py.
//!
//! Run with: cargo run --example v2_chains

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpLlmProvider, ResearchProvider};
use swe_native::{parse_json_str, Json};

const QUESTIONS: [&str; 5] = ["g2-15", "g2-17", "g2-29", "g2-20", "g2-23"];

fn golden_question(qid: &str) -> (String, String) {
    let source = std::fs::read_to_string("benchmarks/golden_v2.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    for q in json.get("questions").and_then(Json::as_array).unwrap() {
        if q.get("id").and_then(Json::as_str) == Some(qid) {
            return (
                q.get("question")
                    .and_then(Json::as_str)
                    .unwrap()
                    .to_string(),
                q.get("conclusion")
                    .and_then(Json::as_str)
                    .unwrap()
                    .to_string(),
            );
        }
    }
    panic!("{qid} saknas");
}

fn bench_texts() -> std::collections::HashMap<String, String> {
    let bench = load_bench_file("benchmarks/bench_real_v2.json").expect("real bench must load");
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

fn main() {
    let llm_key = resolve_secret("CEREBRAS_API_KEY", "../../backend/.env")
        .expect("CEREBRAS_API_KEY saknas (sätt i miljön eller backend/.env)");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());
    let texts = bench_texts();
    std::fs::create_dir_all("benchmarks/chain_synthesis").expect("dir");

    let mut out: Vec<String> = Vec::new();
    for qid in QUESTIONS {
        let (question, _conclusion) = golden_question(qid);
        let hits = jev_hits(qid);
        let evidence_text = hits
            .iter()
            .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
            .collect::<Vec<_>>()
            .join("\n\n");

        // Chain C: synthesize from JEV's evidence.
        let synth = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
            "Du besvarar en juridisk fråga utifrån given evidens från avtalsdokument. Svara kort och exakt, utan motivering.",
        );
        let c_answer = synth
            .analyze(
                "deep",
                "chain-c",
                &format!("Fråga: {question}\n\nEvidens:\n{evidence_text}"),
            )
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Chain D step 1: which concepts must a text contain?
        let needs = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
            "Du identifierar vilka nyckelbegrepp som måste finnas i en text för att besvara en fråga. Svara med en kommaseparerad lista av svenska nyckelord, inget annat.",
        );
        let needs_answer = needs
            .analyze("deep", "chain-d-needs", &format!("Fråga: {question}"))
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        // Chain D step 2: synthesize from the JEV evidence of the filtered set.
        let filtered = hits
            .iter()
            .filter(|c| {
                let text = texts.get(*c).cloned().unwrap_or_default().to_lowercase();
                needs_answer
                    .to_lowercase()
                    .split(',')
                    .map(|k| k.trim())
                    .filter(|k| !k.is_empty())
                    .any(|k| text.contains(k))
            })
            .cloned()
            .collect::<Vec<_>>();
        let d_evidence = filtered
            .iter()
            .map(|c| format!("[{c}]\n{}", texts.get(c).cloned().unwrap_or_default()))
            .collect::<Vec<_>>()
            .join("\n\n");
        let d_answer = synth
            .analyze(
                "deep",
                "chain-d-synth",
                &format!("Fråga: {question}\n\nEvidens:\n{d_evidence}"),
            )
            .map(|a| a.choice)
            .unwrap_or_else(|e| format!("FEL: {e}"));

        out.push(format!(
            "=== {qid}\nQUESTION: {question}\nCHAIN_C: {c_answer}\nCHAIN_D_NEEDS: {needs_answer}\nCHAIN_D: {d_answer}\n"
        ));
        println!("{qid}: C och D fångade");
    }
    std::fs::write("benchmarks/chain_synthesis/answers.txt", out.join("\n")).unwrap();
    println!("klart");
}
