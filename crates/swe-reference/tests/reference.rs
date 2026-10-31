//! Integration tests for the supplier-selection reference experiment.
//!
//! They exercise the crate only through its public API: the embedded SWD
//! definition, the host driver, the reused Sweycoin ledger and the journal.

use std::path::PathBuf;

use swe_reference::{
    all_required, candidates, cheapest_compliant, question, read_journal, resume, run,
    workflow_document, workflow_document_sha256, workflow_input, write_journal, ActionKind,
    Evidence, EvidenceSet, EvidenceStatus, InvocationLog, Json, Need, NeedRef, OpOutcome,
    ResumeConfig, RunConfig, RunReport, RunStatus, Scenario, NO_COMPLIANT_SUPPLIER,
};

fn document() -> Json {
    workflow_document()
}

fn input() -> Json {
    workflow_input(question(), &candidates())
}

fn run_scenario(scenario: Scenario, run_id: &str) -> RunReport {
    run(
        &document(),
        &input(),
        scenario,
        &RunConfig::new(run_id, 100_000),
    )
    .expect("run starts")
    .into_finished()
    .expect("run finishes")
}

fn journal_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "swe-reference-test-{name}-{}.json",
        std::process::id()
    ))
}

fn conclusion_u64(report: &RunReport, key: &str) -> u64 {
    report
        .conclusion
        .as_ref()
        .and_then(|conclusion| conclusion.get(key))
        .and_then(Json::as_number)
        .and_then(|number| number.as_u64())
        .unwrap_or(0)
}

fn verified(need_id: &str, supplier: &str, fact: &str, value: Json) -> Evidence {
    Evidence {
        need_id: need_id.to_string(),
        supplier: supplier.to_string(),
        fact: fact.to_string(),
        status: EvidenceStatus::Verified,
        value,
        source_ref: Some(format!("mock://supplier-register/v1/{supplier}/{fact}")),
        confidence_bp: 9_500,
        reason: "test evidence".to_string(),
    }
}

#[test]
fn conclusion_is_beta() {
    let report = run_scenario(Scenario::Baseline, "test-beta");
    assert_eq!(report.status, RunStatus::Completed);
    assert_eq!(report.conclusion_str("conclusion"), Some("Beta"));
    assert_eq!(report.conclusion_str("conclusion_id"), Some("beta"));
    assert_eq!(conclusion_u64(&report, "price_sek"), 950);
    assert_eq!(report.evidence.len(), 13);
    assert!(report.evidence.iter().all(Evidence::is_verified));
    assert!(report
        .evidence
        .iter()
        .all(|evidence| evidence.source_ref.is_some()));
}

#[test]
fn needs_are_derived_from_operation_contracts_not_data() {
    let checkpoint = RunConfig::new("test-plan", 100_000).with_pause_at_spend(1_200);
    let paused = run(&document(), &input(), Scenario::Baseline, &checkpoint)
        .expect("run starts")
        .paused()
        .expect("the checkpoint pauses right after the plan")
        .clone();
    assert_eq!(paused.journal.completed.len(), 1);
    assert_eq!(paused.journal.completed[0].node_id, "plan");
    assert!(paused
        .segment
        .charges
        .iter()
        .all(|charge| charge.action == "reference.plan_needs"));
    assert_eq!(paused.segment.spent_milli, 1_000);

    let plan = &paused.journal.completed[0].output;
    let needs_compliance = plan
        .get("needs_compliance")
        .and_then(Json::as_array)
        .expect("compliance needs");
    let needs_prices = plan
        .get("needs_prices")
        .and_then(Json::as_array)
        .expect("price needs");
    assert_eq!(needs_compliance.len(), 9);
    assert_eq!(needs_prices.len(), 3);
    for need in needs_compliance.iter().chain(needs_prices.iter()) {
        assert!(need.get("id").and_then(Json::as_str).is_some());
        assert_ne!(
            need.get("fact").and_then(Json::as_str),
            Some("c_exception"),
            "conditional facts are discovered later, not planned from data"
        );
    }
    let operations = plan
        .get("operations")
        .and_then(Json::as_array)
        .expect("operations");
    assert_eq!(operations.len(), 2);

    // The exact same need list is planned for the scenario whose register is
    // damaged: needs come from contracts, not from what the provider happens to
    // return.
    let damaged_pause = run(
        &document(),
        &input(),
        Scenario::MissingEvidence,
        &checkpoint,
    )
    .expect("run starts")
    .paused()
    .expect("the checkpoint pauses right after the plan")
    .clone();
    assert_eq!(
        damaged_pause.journal.completed[0].output,
        paused.journal.completed[0].output
    );
}

#[test]
fn missing_and_ambiguous_evidence_abstains() {
    let report = run_scenario(Scenario::MissingEvidence, "test-abstain");
    assert_eq!(report.status, RunStatus::Incomplete);
    assert_eq!(
        report.conclusion_str("conclusion"),
        Some("INSUFFICIENT_EVIDENCE")
    );
    let reason = report.conclusion_str("reason").expect("abstain reason");
    assert!(reason.contains("ALL_REQUIRED"));
    assert!(reason.contains("beta.req_c"));

    let rejected: Vec<&Evidence> = report
        .evidence
        .iter()
        .filter(|evidence| evidence.status == EvidenceStatus::Rejected)
        .collect();
    assert_eq!(rejected.len(), 1);
    assert_eq!(rejected[0].need_id, "beta.req_c");

    let ambiguous: Vec<&Evidence> = report
        .evidence
        .iter()
        .filter(|evidence| evidence.status == EvidenceStatus::Ambiguous)
        .collect();
    assert_eq!(ambiguous.len(), 1);
    assert_eq!(ambiguous[0].need_id, "gamma.price");

    // The price operation must never run when screening cannot be gated.
    assert!(report
        .invocations
        .iter()
        .all(|invocation| invocation.node_id != "price"));
}

#[test]
fn no_compliant_supplier_is_a_terminal_report_not_a_crash() {
    let report = run_scenario(Scenario::NoCompliantSupplier, "test-no-compliant");
    assert_eq!(report.status, RunStatus::Completed);
    assert_eq!(
        report.conclusion_str("conclusion"),
        Some(NO_COMPLIANT_SUPPLIER)
    );
    let conclusion = report.conclusion.as_ref().expect("terminal report");
    assert_eq!(conclusion.get("conclusion_id"), Some(&Json::Null));
    assert_eq!(conclusion.get("price_sek"), Some(&Json::Null));

    // Every fact was verified; screening completed and listed nobody.
    assert!(report.evidence.iter().all(Evidence::is_verified));
    let screens: Vec<&InvocationLog> = report
        .invocations
        .iter()
        .filter(|invocation| invocation.node_id == "screen")
        .collect();
    let compliant = screens
        .last()
        .and_then(|screen| screen.output.get("compliant"))
        .and_then(Json::as_array)
        .expect("compliant list");
    assert!(compliant.is_empty());

    // The comparison ran on an empty candidate set and the report still built.
    let price = report
        .invocations
        .iter()
        .find(|invocation| invocation.node_id == "price")
        .expect("price operation ran");
    assert_eq!(price.status(), Some("ok"));
    assert_eq!(price.output.get("answer"), Some(&Json::Null));
}

#[test]
fn need_more_is_resolved_and_operation_reruns() {
    let report = run_scenario(Scenario::Baseline, "test-need-more");
    let screens: Vec<&InvocationLog> = report
        .invocations
        .iter()
        .filter(|invocation| invocation.node_id == "screen")
        .collect();
    assert_eq!(screens.len(), 2);
    assert_eq!(screens[0].status(), Some("need_more"));
    let needs = screens[0]
        .output
        .get("needs")
        .and_then(Json::as_array)
        .expect("NeedMore needs");
    assert!(needs
        .iter()
        .any(|need| { need.get("id").and_then(Json::as_str) == Some("alpha.c_exception") }));
    assert_eq!(screens[1].status(), Some("ok"));
    let compliant = screens[1]
        .output
        .get("compliant")
        .and_then(Json::as_array)
        .expect("compliant list");
    assert_eq!(compliant.len(), 1);
    assert_eq!(compliant[0].as_str(), Some("beta"));

    let exception = report
        .evidence
        .iter()
        .find(|evidence| evidence.need_id == "alpha.c_exception")
        .expect("the discovered need was resolved");
    assert!(exception.is_verified());
    assert!(exception
        .source_ref
        .as_deref()
        .expect("provenance")
        .contains("alpha/c_exception"));
    assert_eq!(report.charge_count("reference.screen_compliance"), 2);
}

#[test]
fn all_required_gate_lists_every_missing_input() {
    let required = vec![
        NeedRef::new("alpha", "price"),
        NeedRef::new("beta", "price"),
    ];
    let mut evidence = EvidenceSet::new();

    let gate = all_required(&required, &evidence);
    assert!(!gate.satisfied());
    assert_eq!(gate.missing.len(), 2);
    assert!(gate.summary().contains("alpha.price"));

    evidence.insert(verified(
        "alpha.price",
        "alpha",
        "price",
        Json::from_u64(800),
    ));
    let gate = all_required(&required, &evidence);
    assert!(!gate.satisfied());
    assert_eq!(gate.missing.len(), 1);
    assert_eq!(gate.missing[0].need.id, "beta.price");

    let mut ambiguous = verified("beta.price", "beta", "price", Json::from_u64(950));
    ambiguous.status = EvidenceStatus::Ambiguous;
    evidence.insert(ambiguous);
    let gate = all_required(&required, &evidence);
    assert!(
        !gate.satisfied(),
        "AMBIGUOUS is not accepted by the ALL_REQUIRED gate"
    );
    assert_eq!(gate.missing.len(), 1);
    assert!(gate.missing[0].reason.contains("AMBIGUOUS"));
}

#[test]
fn deterministic_comparison_prefers_cheapest_compliant() {
    let list = candidates();
    let mut evidence = EvidenceSet::new();
    evidence.insert(verified(
        "alpha.price",
        "alpha",
        "price",
        Json::from_u64(800),
    ));
    evidence.insert(verified("beta.price", "beta", "price", Json::from_u64(950)));
    evidence.insert(verified(
        "gamma.price",
        "gamma",
        "price",
        Json::from_u64(900),
    ));

    let ranked = cheapest_compliant(&list, &["beta".to_string(), "gamma".to_string()], &evidence)
        .expect("comparison runs");
    assert_eq!(
        ranked
            .iter()
            .map(|supplier| supplier.id.as_str())
            .collect::<Vec<_>>(),
        ["gamma", "beta"]
    );

    let ranked = cheapest_compliant(
        &list,
        &["alpha".to_string(), "beta".to_string(), "gamma".to_string()],
        &evidence,
    )
    .expect("comparison runs");
    assert_eq!(ranked[0].id, "alpha");
    assert_eq!(ranked[0].price_sek, 800);

    // Equal prices are tie-broken by id, so map completion order never decides.
    let mut tied = evidence.clone();
    tied.insert(verified(
        "gamma.price",
        "gamma",
        "price",
        Json::from_u64(800),
    ));
    let ranked = cheapest_compliant(&list, &["alpha".to_string(), "gamma".to_string()], &tied)
        .expect("comparison runs");
    assert_eq!(ranked[0].id, "alpha");
    assert_eq!(ranked[1].id, "gamma");
}

#[test]
fn pause_and_resume_charge_and_execute_exactly_once() {
    let full = run_scenario(Scenario::Baseline, "test-resume");
    assert_eq!(full.status, RunStatus::Completed);

    let paused_outcome = run(
        &document(),
        &input(),
        Scenario::Baseline,
        &RunConfig::new("test-resume", 100_000).with_pause_at_spend(20_000),
    )
    .expect("run starts");
    let paused = paused_outcome.paused().expect("tight budget pauses");
    assert!(paused.segment.executed_invocations > 0);
    assert!(paused.segment.executed_invocations < full.executed_invocations);
    assert!(paused.segment.spent_milli <= 20_000);
    assert_eq!(
        paused.journal.completed.len(),
        paused.segment.executed_invocations
    );

    let path = journal_path("pause-resume");
    write_journal(&path, &paused.journal).expect("journal is written");
    let loaded = read_journal(&path).expect("journal is read back");
    std::fs::remove_file(&path).expect("journal file removed");

    assert_eq!(
        loaded.definition_sha256,
        workflow_document_sha256().expect("definition hash")
    );
    assert_eq!(loaded.input, paused.journal.input);
    assert_eq!(loaded.completed, paused.journal.completed);
    assert_eq!(loaded.charges, paused.journal.charges);
    assert_eq!(loaded.ledger_events, paused.journal.ledger_events);

    let resumed = resume(&loaded, &ResumeConfig::new())
        .expect("resume starts")
        .into_finished()
        .expect("resume finishes");
    assert_eq!(resumed.status, RunStatus::Completed);
    assert_eq!(resumed.conclusion_str("conclusion"), Some("Beta"));

    // Exactly-once: same total spend, same unique executions, same charges and
    // the same ledger event log as the uninterrupted run.
    assert_eq!(resumed.spent_milli, full.spent_milli);
    assert_eq!(resumed.executed_invocations, full.executed_invocations);
    assert_eq!(resumed.handler_calls, full.handler_calls);
    assert_eq!(resumed.provider_calls, full.provider_calls);
    assert_eq!(resumed.charges, full.charges);
    assert_eq!(resumed.ledger.events(), full.ledger.events());
    assert_eq!(resumed.replayed_invocations, loaded.completed.len());
    assert_eq!(
        resumed.executed_invocations - resumed.replayed_invocations,
        full.executed_invocations - loaded.completed.len()
    );
}

#[test]
fn a_journal_from_another_contract_version_is_refused() {
    let paused_outcome = run(
        &document(),
        &input(),
        Scenario::Baseline,
        &RunConfig::new("test-version", 100_000).with_pause_at_spend(20_000),
    )
    .expect("run starts");
    let paused = paused_outcome.paused().expect("tight budget pauses");

    let mut wrong_contract = paused.journal.clone();
    wrong_contract.contract_version = 999;
    let path = journal_path("contract-version");
    write_journal(&path, &wrong_contract).expect("journal written");
    let loaded = read_journal(&path).expect("journal read");
    std::fs::remove_file(&path).expect("removed");
    let outcome = resume(&loaded, &ResumeConfig::new());
    assert!(
        outcome.is_err(),
        "a changed contract version must not resume"
    );
    assert!(
        format!("{}", outcome.unwrap_err()).contains("version"),
        "the refusal must name the version"
    );
}

#[test]
fn a_journal_whose_definition_changed_is_refused() {
    let paused_outcome = run(
        &document(),
        &input(),
        Scenario::Baseline,
        &RunConfig::new("test-def", 100_000).with_pause_at_spend(20_000),
    )
    .expect("run starts");
    let paused = paused_outcome.paused().expect("tight budget pauses");

    let mut tampered = paused.journal.clone();
    // A well-formed hash that is not this document's hash.
    tampered.definition_sha256 = "b".repeat(64);
    let path = journal_path("def");
    write_journal(&path, &tampered).expect("journal written");
    let loaded = read_journal(&path).expect("journal read");
    std::fs::remove_file(&path).expect("removed");
    assert!(resume(&loaded, &ResumeConfig::new()).is_err());
}

#[test]
fn every_critical_transition_survives_a_pause_and_resume() {
    // Pause after each metered action in turn: the resumed run must reach the
    // same conclusion and the same spend as an uninterrupted one.
    let full = run_scenario(Scenario::Baseline, "test-every-transition");
    assert_eq!(full.status, RunStatus::Completed);
    let mut checked = 0;
    for checkpoint in (1_000..=20_000).step_by(1_000) {
        let paused_outcome = run(
            &document(),
            &input(),
            Scenario::Baseline,
            &RunConfig::new("test-every-transition", 100_000).with_pause_at_spend(checkpoint),
        )
        .expect("run starts");
        let Some(paused) = paused_outcome.paused() else {
            continue;
        };
        // Only meaningful when the checkpoint actually stopped mid-investigation.
        assert!(!paused.journal.completed.is_empty());
        let resumed = resume(&paused.journal, &ResumeConfig::new())
            .expect("resume starts")
            .into_finished()
            .expect("resume finishes");
        assert_eq!(resumed.status, RunStatus::Completed, "at {checkpoint}");
        assert_eq!(
            resumed.conclusion_str("conclusion"),
            full.conclusion_str("conclusion"),
            "at {checkpoint}"
        );
        assert_eq!(resumed.spent_milli, full.spent_milli, "at {checkpoint}");
        assert_eq!(
            resumed.executed_invocations, full.executed_invocations,
            "at {checkpoint}"
        );
        checked += 1;
    }
    assert!(checked >= 5, "expected several pause points, got {checked}");
}

#[test]
fn a_tampered_journal_is_rejected() {
    let paused_outcome = run(
        &document(),
        &input(),
        Scenario::Baseline,
        &RunConfig::new("test-tamper", 100_000).with_pause_at_spend(20_000),
    )
    .expect("run starts");
    let paused = paused_outcome.paused().expect("tight budget pauses");
    let mut tampered = paused.journal.clone();
    tampered.definition_sha256 = "0".repeat(64);

    let path = journal_path("tamper");
    write_journal(&path, &tampered).expect("journal is written");
    let loaded = read_journal(&path).expect("journal is read back");
    std::fs::remove_file(&path).expect("journal file removed");
    assert!(resume(&loaded, &ResumeConfig::new()).is_err());
}

#[test]
fn repeated_runs_are_deterministic() {
    let first = run_scenario(Scenario::Baseline, "test-deterministic");
    let second = run_scenario(Scenario::Baseline, "test-deterministic");
    assert_eq!(first.conclusion, second.conclusion);
    assert_eq!(first.evidence, second.evidence);
    assert_eq!(first.charges, second.charges);
    assert_eq!(first.ledger.events(), second.ledger.events());
    assert_eq!(first.spent_milli, second.spent_milli);
    assert_eq!(first.steps_used, second.steps_used);
    assert_eq!(first.invocations.len(), second.invocations.len());
}

#[test]
fn metering_is_per_action_and_sums_to_the_ledger() {
    let report = run_scenario(Scenario::Baseline, "test-metering");
    let per_action: u64 = report.action_totals().iter().map(|(_, total)| *total).sum();
    assert_eq!(per_action, report.spent_milli);
    assert_eq!(
        report.spent_milli + report.available_milli,
        report.allocated_milli
    );
    assert_eq!(report.ledger_events, report.ledger.events().len());
    assert_eq!(report.provider_calls, 13);
    assert_eq!(report.handler_calls, 20);
    assert_eq!(report.charge_count("mock.supplier_facts"), 13);
    assert_eq!(
        report
            .charges
            .iter()
            .filter(|charge| charge.kind == ActionKind::Handler)
            .count(),
        report.handler_calls
    );
    assert!(report.action_total("reference.screen_compliance") > 0);
}

#[test]
fn need_more_is_a_typed_operation_outcome() {
    let need = Need::new(
        NeedRef::new("alpha", "c_exception"),
        "the static contract does not cover this conditional fact",
    );
    let outcome = OpOutcome::NeedMore(vec![need]);
    assert_eq!(outcome.status(), "need_more");
    let json = outcome.into_json();
    assert_eq!(json.get("status").and_then(Json::as_str), Some("need_more"));
    let needs = json.get("needs").and_then(Json::as_array).expect("needs");
    assert_eq!(needs.len(), 1);
    assert_eq!(
        needs[0].get("id").and_then(Json::as_str),
        Some("alpha.c_exception")
    );
}
