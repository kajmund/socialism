//! Gym driver shell: runs a compiled SWD workflow on the swe-native kernel,
//! metering every provider call against a Sweycoin budget.
//!
//! No external services — providers are pure functions. The dispatch loop is
//! the checkpoint: the kernel is host-paced, so the meter sits between the
//! kernel and the provider call, exactly where a real JEV/LLM client would
//! plug in later.
//!
//! Budget exhaustion is a first-class, loud outcome: the invocation fails with
//! a typed error and the run reaches a terminal status. Nothing is faked, no
//! fallback runs.

use swe_native::{parse_json_str, sha256_hex, start_run, Effect, Json, RunStatus, RuntimeError};

use crate::ledger::{Amount, Ledger, LedgerError};

pub const ROOT_ACCOUNT: &str = "root";

#[derive(Clone, Debug)]
pub struct CallRecord {
    pub account: String,
    pub provider: String,
    pub chunk: String,
    pub choice: String,
    /// Provider confidence in basis points (0..10_000). Facit-free provider
    /// metadata; 0 when the call path has no score model.
    pub score_bp: u32,
    pub cost_milli: Amount,
}

#[derive(Clone, Debug)]
pub struct RunReport {
    pub status: RunStatus,
    pub error: Option<String>,
    pub calls: Vec<CallRecord>,
    pub denied: Vec<String>,
    pub spent_milli: Amount,
    pub available_milli: Amount,
    pub machine_events: usize,
    pub ledger_events: usize,
    pub ledger: Ledger,
}

/// Drive `document` to a terminal state with a hard Sweycoin budget.
///
/// `ground_truth` answers "does this chunk contain evidence" for the fake
/// analyzer; it lives outside the workflow, exactly as real ground truth does.
pub fn run_with_budget(
    document: &str,
    run_id: &str,
    input: &str,
    budget_milli: Amount,
    tariff_milli: Amount,
    ground_truth: &dyn Fn(&str) -> Option<bool>,
) -> Result<RunReport, String> {
    let document = parse_json_str(document).map_err(|error| error.to_string())?;
    let sha = sha256_hex(&document).map_err(|error| error.to_string())?;
    let input = parse_json_str(input).map_err(|error| error.to_string())?;

    let (mut machine, mut outcome) = start_run(document, &sha, run_id.to_string(), input, 1_000)
        .map_err(|error| error.to_string())?;

    let mut ledger = Ledger::new();
    ledger
        .allocate(
            run_id,
            ROOT_ACCOUNT,
            budget_milli,
            &format!("{run_id}:allocate"),
        )
        .map_err(|error| error.to_string())?;

    let mut report = RunReport {
        status: RunStatus::Running,
        error: None,
        calls: Vec::new(),
        denied: Vec::new(),
        spent_milli: 0,
        available_milli: budget_milli,
        machine_events: 0,
        ledger_events: 0,
        ledger: Ledger::new(),
    };

    loop {
        if outcome.status.is_terminal() {
            break;
        }
        let effects = std::mem::take(&mut outcome.effects);
        if effects.is_empty() {
            outcome = machine.tick(1_000);
            if !outcome.status.is_terminal() && outcome.effects.is_empty() {
                report.error = Some("stalled: kernel is running without pending effects".into());
                break;
            }
            continue;
        }
        for effect in effects {
            match effect {
                Effect::InvokeProvider {
                    invocation_id,
                    provider,
                    input,
                    ..
                } => {
                    let chunk = input
                        .get("chunk")
                        .and_then(Json::as_str)
                        .unwrap_or("?")
                        .to_string();
                    let reserve_key = format!("{run_id}:invoke:{invocation_id}");
                    match ledger.reserve(run_id, ROOT_ACCOUNT, tariff_milli, &reserve_key) {
                        Ok(reservation_id) => {
                            let choice = fake_analyze(&provider, &chunk, ground_truth);
                            ledger
                                .settle(
                                    reservation_id,
                                    tariff_milli,
                                    &format!("{run_id}:settle:{invocation_id}"),
                                )
                                .map_err(|error| error.to_string())?;
                            report.calls.push(CallRecord {
                                account: ROOT_ACCOUNT.to_string(),
                                provider,
                                chunk,
                                choice: choice.clone(),
                                score_bp: 0,
                                cost_milli: tariff_milli,
                            });
                            outcome = machine.complete(
                                &invocation_id,
                                Json::object([
                                    ("choice".to_string(), Json::from(choice.as_str())),
                                    ("cache".to_string(), Json::from("miss")),
                                ]),
                                1_000,
                            );
                        }
                        Err(LedgerError::InsufficientFunds { .. }) => {
                            report.denied.push(chunk);
                            outcome = machine.fail(
                                &invocation_id,
                                RuntimeError::limit(format!(
                                    "sweycoin budget exhausted for provider {provider:?}"
                                )),
                                1_000,
                            );
                        }
                        Err(other) => {
                            report.denied.push(chunk);
                            outcome = machine.fail(
                                &invocation_id,
                                RuntimeError::internal(format!("ledger error: {other}")),
                                1_000,
                            );
                        }
                    }
                }
                Effect::InvokeHandler { invocation_id, .. } => {
                    outcome = machine.fail(
                        &invocation_id,
                        RuntimeError::unsupported("handlers are not part of the gym PoC"),
                        1_000,
                    );
                }
                Effect::CancelInvocation { .. } => {
                    report.error = Some("unexpected CancelInvocation effect".into());
                    outcome = machine.cancel(1_000);
                }
            }
        }
    }

    report.status = machine.status();
    if let Some(error) = machine.error() {
        report.error = Some(error.message.clone());
    }
    let balance = ledger.balance(ROOT_ACCOUNT);
    report.spent_milli = balance.spent;
    report.available_milli = balance.available();
    report.machine_events = machine.events().len();
    report.ledger_events = ledger.events().len();
    report.ledger = ledger;
    Ok(report)
}

/// Deterministic stand-in for a JEV/LLM analyzer. `ground_truth` is the
/// experiment's corpus answer table; the provider itself is a pure function.
pub fn fake_analyze(
    provider: &str,
    chunk: &str,
    ground_truth: &dyn Fn(&str) -> Option<bool>,
) -> String {
    debug_assert_eq!(provider, "analyze", "PoC registers a single provider");
    match ground_truth(chunk) {
        Some(true) => "fynd".into(),
        _ => "inget".into(),
    }
}

/// Build a linear chain of `chunk_count` provider-decision nodes, each
/// analyzing one chunk. The chain is the smallest SWD shape that exercises
/// many metered calls; a map node can replace it once branches are in scope.
pub fn build_chain_document(chunk_count: usize) -> String {
    build_chain_document_for("analyze", chunk_count)
}

/// Chain document with an explicit provider name, for benchmark branches.
pub fn build_chain_document_for(provider: &str, chunk_count: usize) -> String {
    let mut nodes = String::new();
    for i in 0..chunk_count {
        let next = if i + 1 < chunk_count {
            format!("analyze_{}", i + 1)
        } else {
            "done".to_string()
        };
        nodes.push_str(&format!(
            r#""analyze_{i}":{{"type":"decision","evaluator":"provider","provider":"{provider}","prompt_key":"demo.{provider}","input":{{"chunk":"$.input.chunks.{i}.id","text":"$.input.chunks.{i}.text"}},"choices":["fynd","inget"],"routes":{{"fynd":"{next}","inget":"{next}"}},"cache_policy":"off"}},"#
        ));
    }
    // Kernel steps, not provider calls: each chain node consumes several
    // steps (invoke, complete, route, events). Headroom per chunk x8.
    let max_steps = chunk_count.saturating_mul(8).saturating_add(32).max(100) as u32;
    format!(
        r#"{{"version":"1.0","name":"sweycoin_demo","entrypoint":"analyze_0","limits":{{"max_steps":{max_steps},"max_depth":4,"timeout_seconds":30}},"nodes":{{{nodes}"done":{{"type":"end","status":"completed"}}}}}}"#
    )
}

/// Input document with `chunk_count` chunks named `chunk-00` .. `chunk-NN`.
pub fn build_chunk_input(chunk_count: usize) -> String {
    let ids: Vec<String> = (0..chunk_count).map(|i| format!("chunk-{i:02}")).collect();
    let chunks: Vec<&str> = ids.iter().map(String::as_str).collect();
    build_chunk_input_for(&chunks)
}

/// Input document for an explicit, ordered chunk list.
pub fn build_chunk_input_for(chunks: &[&str]) -> String {
    build_chunk_input_with_texts(chunks, &std::collections::HashMap::new())
}

/// Input document with real chunk texts; missing entries fall back to the
/// placeholder so synthetic questions keep working.
pub fn build_chunk_input_with_texts(
    chunks: &[&str],
    texts: &std::collections::HashMap<String, String>,
) -> String {
    let chunks = chunks
        .iter()
        .map(|chunk| {
            let text = texts
                .get(*chunk)
                .cloned()
                .unwrap_or_else(|| format!("lorem ipsum {chunk}"));
            format!(
                r#"{{"id":"{}","text":"{}"}}"#,
                chunk,
                crate::provider::json_escape(&text),
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    format!(r#"{{"chunks":[{chunks}]}}"#)
}
