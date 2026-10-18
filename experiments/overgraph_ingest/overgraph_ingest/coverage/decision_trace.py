"""Per-document EVIDENCE_FOUND traces. Does not change v3, C@8, or LINK_RE."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from overgraph_ingest.coverage.proof import COMPOSITE, EXISTS
from overgraph_ingest.coverage.proof_link import LINKED_RELATION, evaluate_passage
from overgraph_ingest.coverage.proof_relation import PROOF_CURRENT
from overgraph_ingest.coverage.state import EVIDENCE_FOUND, DocumentState, UnitRecord, resolve_status
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit

ROOT = Path(__file__).resolve().parents[2]
TRACE_BASELINE_ID = "phase2-decision-trace-v1"
TRACE_BASELINE_PATH = ROOT / "baselines" / f"{TRACE_BASELINE_ID}.json"
BLIND_RUN_CANDIDATES = (
    ROOT / "data" / "coverage-v3-blind.json",
    ROOT / "data" / "blind-coverage-v3.json",
    ROOT / "data" / "coverage-v3-contracts-v2.json",
    ROOT / "data" / "coverage-v3-blind-trace.json",
)


def found_reason(doc: DocumentState, *, proof_kind: str, proof_rule: str) -> str | None:
    if doc.status != EVIDENCE_FOUND:
        return None
    if proof_kind == EXISTS and doc.yes_count():
        return "exists_jev_yes"
    if proof_kind == COMPOSITE and proof_rule == PROOF_CURRENT:
        if doc.required_parts and doc.parts_complete():
            return "required_parts_complete"
        if doc.yes_count() and doc.hop_attempted:
            return "jev_yes_after_hop"
        if doc.yes_count():
            return "jev_yes_without_pending_hop"
    if doc.yes_count():
        return f"jev_yes_under_{proof_rule}"
    return "unknown"


def unit_identity(row: UnitRecord, unit: StoredUnit | None = None) -> dict[str, object]:
    text = row.text or ("" if unit is None else unit.text)
    return {
        "key": row.key,
        "node_id": None if unit is None else unit.node_id,
        "document_id": None if unit is None else unit.document_id,
        "relative_path": None if unit is None else unit.relative_path,
        "structure_id": None if unit is None else unit.structure_id,
        "sequence": None if unit is None else unit.sequence,
        "char_start": None if unit is None else unit.char_start,
        "char_end": None if unit is None else unit.char_end,
        "content_hash": None if unit is None else unit.content_hash,
        "text_sha256": sha256(text.encode("utf-8")).hexdigest() if text else None,
    }


def prefix_before_navigation(doc: DocumentState) -> list[UnitRecord]:
    rows: list[UnitRecord] = []
    for row in doc.retrieved:
        if row.hop:
            break
        rows.append(row)
    return rows


def controller_status_before_navigation(
    doc: DocumentState,
    *,
    proof_kind: str,
    proof_rule: str,
    budget: int | None = None,
) -> str:
    clone = DocumentState(
        relative_path=doc.relative_path,
        document_units=doc.document_units,
        retrieved=list(prefix_before_navigation(doc)),
        hop_attempted=False,
        required_parts=doc.required_parts,
    )
    return resolve_status(clone, proof_kind=proof_kind, proof_rule=proof_rule, budget=budget)


def trace_document(
    doc: DocumentState,
    *,
    query: str,
    gold_id: str,
    proof_kind: str,
    proof_rule: str = PROOF_CURRENT,
    relevant: bool,
    gold_span: str | None = None,
    gold_classification: str | None = None,
    gold_trap: str | None = None,
    units_by_key: dict[str, StoredUnit] | None = None,
    budget: int | None = None,
) -> dict[str, object]:
    lookup = units_by_key or {}
    yes_units = [row for row in doc.retrieved if row.predicted == "YES"]
    hops = [row for row in doc.retrieved if row.hop]
    prefix = prefix_before_navigation(doc)
    joined = "\n".join(row.text for row in doc.retrieved if row.text)
    joined_before = "\n".join(row.text for row in prefix if row.text)
    before_status = controller_status_before_navigation(
        doc,
        proof_kind=proof_kind,
        proof_rule=proof_rule,
        budget=budget,
    )
    role = _role(doc.status, relevant=relevant, gold_classification=gold_classification)
    error_class = None
    if role == "false_complete":
        error_class = gold_trap or "unobserved"
    events = [
        _event(index, row, lookup.get(row.key)) for index, row in enumerate(doc.retrieved)
    ]
    events.append(
        {
            "index": len(events),
            "kind": "proof_decision",
            "status": doc.status,
            "why_evidence_found": found_reason(doc, proof_kind=proof_kind, proof_rule=proof_rule),
        }
    )
    return {
        "document_id": doc.relative_path,
        "query": query,
        "gold_id": gold_id,
        "events": events,
        "jev_yes_units": [_unit_row(row, lookup.get(row.key)) for row in yes_units],
        "hops": [_hop_row(row, lookup.get(row.key)) for row in hops],
        "units_used": [_unit_row(row, lookup.get(row.key)) for row in doc.retrieved],
        "why_evidence_found": found_reason(doc, proof_kind=proof_kind, proof_rule=proof_rule),
        "controller_status_before_navigation": before_status,
        "evidence_found_before_navigation": before_status == EVIDENCE_FOUND,
        "navigation_added_necessary_complete": bool(hops)
        and before_status != EVIDENCE_FOUND
        and doc.status == EVIDENCE_FOUND,
        "link_re_matches_before_navigation": evaluate_passage(joined_before)["status"]
        == LINKED_RELATION,
        "link_re_matches": evaluate_passage(joined)["status"] == LINKED_RELATION,
        "required_source_span": gold_span if relevant else None,
        "relation_supported_in_gold": relevant,
        "error_class": error_class,
        "gold_classification": gold_classification,
        "role": role,
        "status": doc.status,
    }


def traces_for_found(
    documents: dict[str, DocumentState],
    gold: RetrievalGold,
    *,
    proof_rule: str = PROOF_CURRENT,
    units_by_key: dict[str, StoredUnit] | None = None,
    gold_classes: dict[str, str] | None = None,
    gold_traps: dict[str, str] | None = None,
    budget: int | None = None,
) -> list[dict[str, object]]:
    relevant = set(gold.relevant_documents)
    classes = gold_classes or {}
    traps = gold_traps or {}
    rows = []
    for path, doc in sorted(documents.items()):
        if doc.status != EVIDENCE_FOUND:
            continue
        rows.append(
            trace_document(
                doc,
                query=gold.query,
                gold_id=gold.id,
                proof_kind=gold.proof_kind,
                proof_rule=proof_rule,
                relevant=path in relevant,
                gold_span=_gold_span(gold, path),
                gold_classification=classes.get(path),
                gold_trap=traps.get(path),
                units_by_key=units_by_key,
                budget=budget,
            )
        )
    return rows


def contrast_cases(
    traces: list[dict[str, object]],
    *,
    false_n: int = 5,
    true_n: int = 5,
) -> dict[str, object]:
    false_complete = [row for row in traces if row.get("role") == "false_complete"]
    true_missed = [
        row
        for row in traces
        if row.get("role") == "true_complete" and not row.get("link_re_matches")
    ]
    return {
        "false_complete": false_complete[:false_n],
        "true_complete_missed_by_detector": true_missed[:true_n],
        "observed_false_complete_count": len(false_complete),
        "observed_true_complete_missed_count": len(true_missed),
        "complete_uncertain_count": sum(1 for row in traces if row.get("role") == "complete_uncertain"),
        "do_not_pad_with_hypotheses": True,
    }


def collect_traces(payload: dict[str, object]) -> list[dict[str, object]]:
    top = payload.get("decision_traces")
    if isinstance(top, list) and top:
        return list(top)
    rows: list[dict[str, object]] = []
    for gold in payload.get("golds") or []:
        if not isinstance(gold, dict):
            continue
        for budget in gold.get("budgets") or []:
            if not isinstance(budget, dict):
                continue
            if budget.get("budget") != 5 and budget.get("variant") != "B5":
                continue
            rows.extend(item for item in (budget.get("decision_traces") or []) if isinstance(item, dict))
    return rows


def inspect_saved_run(payload: dict[str, object]) -> dict[str, object]:
    traces = collect_traces(payload)
    if traces:
        return {
            "observability_gap": False,
            "contrast": contrast_cases(traces),
        }
    named: list[str] = []
    for gold in payload.get("golds") or []:
        if not isinstance(gold, dict):
            continue
        for budget in gold.get("budgets") or []:
            if not isinstance(budget, dict):
                continue
            if budget.get("budget") != 5 and budget.get("variant") != "B5":
                continue
            named.extend(str(path) for path in (budget.get("evidence_found_nonrelevant") or []))
    return {
        "observability_gap": True,
        "named_paths_without_units": sorted(set(named)),
        "cannot_read_jev_yes_unit": True,
        "cannot_read_hop": True,
        "cannot_attribute_error_class": True,
        "do_not_guess_documents": True,
    }


def _role(status: str, *, relevant: bool, gold_classification: str | None) -> str:
    if status != EVIDENCE_FOUND:
        return status
    if gold_classification == "UNCERTAIN":
        return "complete_uncertain"
    if gold_classification == "NO":
        return "false_complete"
    if gold_classification == "YES" or relevant:
        return "true_complete"
    return "false_complete"


def _event(index: int, row: UnitRecord, unit: StoredUnit | None) -> dict[str, object]:
    payload = {
        "index": index,
        "kind": "navigation" if row.hop else "classify",
        "source": row.source,
        "predicted": row.predicted,
        "identity": unit_identity(row, unit),
        "text": row.text,
    }
    if row.hop:
        payload["hop"] = row.hop
    return payload


def _unit_row(row: UnitRecord, unit: StoredUnit | None) -> dict[str, object]:
    return {
        "identity": unit_identity(row, unit),
        "predicted": row.predicted,
        "source": row.source,
        "hop": row.hop,
        "text": row.text,
    }


def _hop_row(row: UnitRecord, unit: StoredUnit | None) -> dict[str, object]:
    return {
        "identity": unit_identity(row, unit),
        "hop": row.hop,
        "text": row.text,
    }


def _gold_span(gold: RetrievalGold, path: str) -> str | None:
    for span in gold.relevant_units:
        if span.relative_path == path:
            return span.contains
    for group in gold.coverage_groups:
        if group.relative_path == path:
            return " | ".join(group.contains)
    return None
