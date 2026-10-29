//! The action market — Level 1 (docs/SWE_Sweycoins_v2.md 27): freeze
//! investigation states (candidate + baseline verdict) and run every
//! applicable action from the SAME state to get a facit of what each
//! investment would have yielded. Live actions: clarified-evidence JEV
//! and clause-context JEV. Offline actions (accept NONE, deterministic
//! extraction) are computed in tools/measure_market.py.
//!
//! Run with: cargo run --example v2_market

use swe_gym::bench::load_bench_file;
use swe_gym::provider::{resolve_secret, HttpJevProvider, ResearchProvider};
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

fn baseline_verdict(qid: &str, chunk: &str) -> String {
    let path = format!("benchmarks/milestone_capture/{qid}-initial.json");
    let source = std::fs::read_to_string(&path).unwrap_or_default();
    if source.is_empty() {
        return "okänd".to_string();
    }
    let json = parse_json_str(&source).unwrap();
    for e in json.get("entries").and_then(Json::as_array).unwrap() {
        if e.get("chunk_id").and_then(Json::as_str) == Some(chunk) {
            return e
                .get("choice")
                .and_then(Json::as_str)
                .unwrap_or("okänd")
                .to_string();
        }
    }
    "ej bedömd".to_string()
}

fn main() {
    let jev_key =
        resolve_secret("TYPESAFE_API_KEY", "../../backend/.env").expect("TYPESAFE_API_KEY saknas");
    let jev_base = resolve_secret("TYPESAFE_BASE_URL", "../../backend/.env")
        .unwrap_or_else(|| "https://api.typesafe.ai".to_string());
    let jev_model = resolve_secret("JEV_MODEL", "../../backend/.env")
        .unwrap_or_else(|| "jev-latest".to_string());

    let texts = bench_texts();
    let rank = ranks();
    std::fs::create_dir_all("benchmarks/action_market").expect("dir");
    let mut out: Vec<String> = Vec::new();
    let mut total_states = 0usize;

    for (qid, question, evidence) in cases() {
        let pool = rank.get(&qid).expect("rank");
        let top8: Vec<String> = pool.iter().take(8).cloned().collect();
        // States: facit evidence chunks + top-8 candidates with a
        // baseline NONE verdict — the decision-relevant frozen states.
        let mut states: Vec<String> = evidence.clone();
        for c in &top8 {
            if !states.contains(c) && baseline_verdict(&qid, c) == "inget" {
                states.push(c.clone());
            }
        }

        let baseline_prompt = format!("{question} Classify only the candidate `text` field. YES only if the candidate text itself contains evidence RELEVANT to answering the question — a text can be necessary evidence without answering the question alone. NO if it does not. If the candidate text is not enough to decide, choose UNCERTAIN.");
        let clarified_prompt = format!("{baseline_prompt} Olika formuleringar är ekvivalenta: 'sägs upp senast X månader före utgång' betyder 'har X månaders uppsägningstid', och 'förlängs om det inte sägs upp' rör också uppsägningstiden.");
        let clarified = HttpJevProvider::new(&jev_key, &jev_base, &jev_model)
            .with_instructions(&clarified_prompt);

        for chunk in &states {
            let text = texts.get(chunk).cloned().unwrap_or_default();
            let doc = chunk.split(':').next().unwrap();
            let clar = clarified
                .analyze("scan", "market-clarified", &text)
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            let heading = text.lines().next().unwrap_or("").to_string();
            let context_text = format!("[Dokument: {doc}]\n[Klausulrubrik: {heading}]\n{text}");
            let ctx_provider = HttpJevProvider::new(&jev_key, &jev_base, &jev_model)
                .with_instructions(&baseline_prompt);
            let ctx = ctx_provider
                .analyze("scan", "market-context", &context_text)
                .map(|a| a.choice)
                .unwrap_or_else(|e| format!("FEL: {e}"));
            out.push(format!(
                "{qid}|{chunk}|{}|{clar}|{ctx}",
                baseline_verdict(&qid, chunk)
            ));
            total_states += 1;
            if total_states % 20 == 0 {
                println!("{total_states} tillstånd...");
            }
        }
    }
    std::fs::write("benchmarks/action_market/states.txt", out.join("\n")).unwrap();
    println!("klart: {total_states} frysta tillstånd");
}
