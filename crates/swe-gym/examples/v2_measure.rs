//! Research Gym measurement capture (docs/SWE_Sweycoins_v2.md 19): run
//! JEV and LLM live over each golden question's candidate set and freeze
//! the answers as fixtures, so the marginal-value analysis is offline and
//! reproducible afterwards. Env-gated; bounded cost (~24 candidates x 30
//! questions x 2 providers).
//!
//! Run with: cargo run --example v2_measure

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{
    resolve_secret, HttpJevProvider, HttpLlmProvider, RecordProvider, ResearchProvider,
};
use swe_native::{parse_json_str, Json};

fn load_golden() -> Vec<(String, String, Vec<String>)> {
    let source = std::fs::read_to_string("benchmarks/golden_v2.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    json.get("questions")
        .and_then(Json::as_array)
        .unwrap()
        .iter()
        .map(|q| {
            let id = q.get("id").and_then(Json::as_str).unwrap().to_string();
            let text = q
                .get("question")
                .and_then(Json::as_str)
                .unwrap()
                .to_string();
            let docs = q
                .get("documents")
                .and_then(Json::as_array)
                .unwrap()
                .iter()
                .map(|d| d.as_str().unwrap().to_string())
                .collect();
            (id, text, docs)
        })
        .collect()
}

fn load_candidates() -> std::collections::HashMap<String, Vec<String>> {
    let source = std::fs::read_to_string("benchmarks/golden_v2_candidates.json").unwrap();
    let json = parse_json_str(&source).unwrap();
    let mut out = std::collections::HashMap::new();
    let cands = json.get("candidates").and_then(Json::as_object).unwrap();
    for (qid, list) in cands {
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

fn main() {
    let jev_key = resolve_secret("TYPESAFE_API_KEY", "../../backend/.env")
        .expect("TYPESAFE_API_KEY saknas (sätt i miljön eller backend/.env)");
    let jev_base = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let jev_model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());
    let llm_key = resolve_secret("CEREBRAS_API_KEY", "../../backend/.env")
        .expect("CEREBRAS_API_KEY saknas (sätt i miljön eller backend/.env)");
    let llm_base = resolve_secret("CEREBRAS_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.cerebras.ai/v1".to_string());

    let bench = load_bench_file("benchmarks/bench_real_v2.json").expect("real bench must load");
    let mut texts = std::collections::HashMap::new();
    for q in &bench.questions {
        for (chunk, text) in &q.texts {
            texts.insert(chunk.clone(), text.clone());
        }
    }

    let golden = load_golden();
    let candidates = load_candidates();
    std::fs::create_dir_all("benchmarks/golden_v2_fixtures").expect("fixture dir");

    let mut total_jev = 0usize;
    let mut total_llm = 0usize;
    let mut invalid: Vec<String> = Vec::new();
    for (qid, question, _docs) in &golden {
        let Some(cands) = candidates.get(qid) else {
            eprintln!("{qid}: candidates saknas");
            continue;
        };
        let jev_path = format!("benchmarks/golden_v2_fixtures/{qid}-jev.json");
        if std::path::Path::new(&jev_path).exists() {
            println!("{qid}: redan fångad — hoppar");
            continue;
        }
        let jev = HttpJevProvider::new(&jev_key, &jev_base, &jev_model).with_instructions(
            &format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence that answers the question. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN."),
        );
        let jev_recorder = RecordProvider::new(&jev);
        let llm = HttpLlmProvider::new(&llm_key, &llm_base, "gpt-oss-120b").with_system_prompt(
            &format!("Du klassificerar avtalstext. Fråga: {question} Svara med exakt ett ord: JA, NEJ eller OSÄKER."),
        );
        let llm_recorder = RecordProvider::new(&llm);

        for chunk in cands {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            // Invalid answers are data, not crashes: a capability that
            // does not follow the answer format is a real capability
            // property, recorded and reported — never retried silently.
            if let Err(e) = jev_recorder.analyze("scan", chunk, &text) {
                invalid.push(format!("{qid} JEV {chunk}: {e}"));
            }
            if let Err(e) = llm_recorder.analyze("deep", chunk, &text) {
                invalid.push(format!("{qid} LLM {chunk}: {e}"));
            }
        }
        total_jev += cands.len();
        total_llm += cands.len();
        std::fs::write(
            format!("benchmarks/golden_v2_fixtures/{qid}-jev.json"),
            jev_recorder.to_fixture_with("swe-gym-golden-v2", question),
        )
        .unwrap();
        std::fs::write(
            format!("benchmarks/golden_v2_fixtures/{qid}-llm.json"),
            llm_recorder.to_fixture_with("swe-gym-golden-v2", question),
        )
        .unwrap();
        println!("{qid}: {} kandidater fångade (JEV + LLM)", cands.len());
    }
    std::fs::write(
        "benchmarks/golden_v2_fixtures/invalid_answers.txt",
        invalid.join("\n"),
    )
    .unwrap();
    println!(
        "klart: {total_jev} JEV-anrop, {total_llm} LLM-anrop, {} ogiltiga svar",
        invalid.len()
    );
}
