"""Freeze observed blind Coverage v3 traces. Does not change proof evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.blind_gold import load_blind_property
from overgraph_ingest.coverage.decision_trace import _role, collect_traces, contrast_cases

ROOT = Path(__file__).resolve().parents[2]
RUN_PATH = ROOT / "data" / "coverage-v3-blind-trace.json"
BLIND_TRACE_BASELINE_ID = "phase2-coverage-v3-blind-trace-v1"
BLIND_TRACE_BASELINE_PATH = ROOT / "baselines" / f"{BLIND_TRACE_BASELINE_ID}.json"
TRUE_PICKS = (
    "avtal_103.docx",
    "avtal_106.docx",
    "avtal_107.docx",
    "avtal_113.docx",
    "avtal_140.docx",
)


def _summary(row: dict[str, object]) -> dict[str, object]:
    yes = list(row.get("jev_yes_units") or [])
    hops = list(row.get("hops") or [])
    first_yes = yes[0] if yes else {}
    identity = first_yes.get("identity") or {}
    return {
        "document_id": row.get("document_id"),
        "gold_classification": row.get("gold_classification"),
        "role": row.get("role"),
        "error_class": row.get("error_class"),
        "why_evidence_found": row.get("why_evidence_found"),
        "controller_status_before_navigation": row.get("controller_status_before_navigation"),
        "evidence_found_before_navigation": row.get("evidence_found_before_navigation"),
        "navigation_added_necessary_complete": row.get("navigation_added_necessary_complete"),
        "link_re_matches_before_navigation": row.get("link_re_matches_before_navigation"),
        "link_re_matches": row.get("link_re_matches"),
        "jev_yes_text": first_yes.get("text"),
        "hop_text": hops[0].get("text") if hops else None,
        "identity": identity,
        "event_kinds": [event.get("kind") for event in list(row.get("events") or [])],
    }


def labeled_traces(payload: dict[str, object]) -> list[dict[str, object]]:
    gold, classes, traps = load_blind_property("E_sekretessundantag_fran_ansvarsbegransning")
    relevant = set(gold.relevant_documents)
    rows = []
    for row in collect_traces(payload):
        path = str(row.get("document_id") or "")
        labeled = dict(row)
        labeled["gold_classification"] = classes.get(path)
        labeled["role"] = _role(
            str(row.get("status") or ""),
            relevant=path in relevant,
            gold_classification=classes.get(path),
        )
        if labeled["role"] == "false_complete":
            labeled["error_class"] = traps.get(path) or "unobserved"
        else:
            labeled["error_class"] = None
        rows.append(labeled)
    return rows


def freeze_blind_trace_baseline(payload: dict[str, object]) -> dict[str, object]:
    gold_row = (payload.get("golds") or [{}])[0]
    budgets = {int(row["budget"]): row for row in gold_row.get("budgets") or [] if "budget" in row}
    b5 = budgets.get(5) or {}
    traces = labeled_traces(payload)
    contrast = contrast_cases(traces)
    by_id = {str(row.get("document_id")): row for row in traces}
    return {
        "id": BLIND_TRACE_BASELINE_ID,
        "label": (
            "Frozen: observed Coverage v3 decision traces on contracts_v2 carve-out. "
            "Do not change proof evaluation from this file."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "no_new_proof_rule": True,
        "no_link_re_change": True,
        "tracing_does_not_change_decisions": True,
        "headline": {
            "documents_found": b5.get("documents_found"),
            "documents_expected": b5.get("documents_expected"),
            "document_recall_b5": b5.get("document_recall"),
            "evidence_found_nonrelevant": b5.get("evidence_found_nonrelevant"),
            "observed_false_complete_count": contrast["observed_false_complete_count"],
            "complete_uncertain_count": contrast["complete_uncertain_count"],
            "observed_true_complete_missed_count": contrast["observed_true_complete_missed_count"],
            "document_coverage_at_50": gold_row.get("document_coverage_at_50"),
            "classified_b5": b5.get("classified"),
            "jev_calls_b5": b5.get("jev_calls"),
            "hop_fetches_b5": b5.get("hop_fetches"),
            "all_found_reasons_jev_yes_after_hop": all(
                row.get("why_evidence_found") == "jev_yes_after_hop" for row in traces
            ),
        },
        "false_complete": [_summary(by_id[path]) for path in ("avtal_119.docx", "avtal_200.docx") if path in by_id],
        "complete_uncertain": [
            _summary(by_id[path])
            for path in ("avtal_138.docx", "avtal_142.docx", "avtal_173.docx")
            if path in by_id
        ],
        "true_complete_missed_by_detector": [
            _summary(by_id[path]) for path in TRUE_PICKS if path in by_id
        ],
        "uncertain_is_not_false_complete": True,
        "do_not_pad_false_completes": True,
    }


def write_blind_trace_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or BLIND_TRACE_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_blind_trace_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
