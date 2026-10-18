"""Rescore hop-always and the chain contract with gold-map v2. No new Jev."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.blind_carveout import GOLD_ZIP
from overgraph_ingest.coverage.blind_gold import load_blind_property
from overgraph_ingest.coverage.chain_contract import (
    CHAIN_CONTRACT,
    HOP_ALWAYS,
    SUPPORTED,
    UNDECIDED,
    assess_chain,
    hop_always_decision,
    unit_events,
)
from overgraph_ingest.coverage.decision_trace import BLIND_RUN_CANDIDATES, collect_traces
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL
from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION, UNIQUE, map_span
from overgraph_ingest.retrieval.index import StoredUnit

ROOT = Path(__file__).resolve().parents[2]
CHAIN_BASELINE_ID = "phase2-decision-contract-v1"
CHAIN_BASELINE_PATH = ROOT / "baselines" / f"{CHAIN_BASELINE_ID}.json"
SAVED_BLIND_TRACE = ROOT / "data" / "coverage-v3-blind-trace.json"


def load_blind_traces(path: Path | None = None) -> list[dict[str, object]]:
    target = path or next((item for item in (SAVED_BLIND_TRACE, *BLIND_RUN_CANDIDATES) if item.is_file()), None)
    if target is None:
        return []
    return collect_traces(json.loads(target.read_text(encoding="utf-8")))


def score_variant(
    traces: list[dict[str, object]],
    decisions: list[dict[str, object]],
    *,
    gold_classes: dict[str, str],
    gold_spans: list[GoldSpan],
    expected_yes: tuple[str, ...],
) -> dict[str, object]:
    by_id = {str(row["document_id"]): row for row in decisions}
    admitted = {
        path for path, row in by_id.items() if row.get("examined_support") == SUPPORTED
    }
    leftover = sorted(path for path in expected_yes if path not in admitted)
    false_approvals = sorted(
        path for path in admitted if gold_classes.get(path) == "NO"
    )
    repaired_uncertain = sorted(
        path for path in admitted if gold_classes.get(path) == "UNCERTAIN"
    )
    true_support = sorted(path for path in admitted if gold_classes.get(path) == "YES")
    passage = _passage_grounding(traces, gold_spans)
    investigations = {str(row["document_id"]): row.get("investigation") for row in decisions}
    return {
        "mapping": GOLD_MAP_VERSION,
        "admitted": sorted(admitted),
        "true_support": true_support,
        "false_approvals": false_approvals,
        "repaired_uncertain": repaired_uncertain,
        "leftover_genuine": leftover,
        "counts": {
            "admitted": len(admitted),
            "true_support": len(true_support),
            "false_approvals": len(false_approvals),
            "repaired_uncertain": len(repaired_uncertain),
            "leftover_genuine": len(leftover),
        },
        "passage_grounded_unique": passage,
        "investigation_complete_from_proof": any(
            value == "COMPLETE" for value in investigations.values()
        ),
        "all_investigations_partial": all(
            value == INVESTIGATION_PARTIAL for value in investigations.values()
        )
        if investigations
        else True,
    }


def run_decision_contract(path: Path | None = None) -> dict[str, object]:
    traces = load_blind_traces(path)
    gold, classes, _traps = _gold()
    expected = tuple(gold.relevant_documents)
    reference = [hop_always_decision(trace) for trace in traces]
    treatment = [assess_chain(trace) for trace in traces]
    ref_score = score_variant(
        traces,
        reference,
        gold_classes=classes,
        gold_spans=gold.relevant_units,
        expected_yes=expected,
    )
    treat_score = score_variant(
        traces,
        treatment,
        gold_classes=classes,
        gold_spans=gold.relevant_units,
        expected_yes=expected,
    )
    by_id = {str(row["document_id"]): row for row in treatment}
    return {
        "operation": "coverage",
        "experiment": "decision_contract_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_rewrite_history": True,
        "applied_to_v3": False,
        "no_new_jev": True,
        "no_new_controller": True,
        "no_looser_verified_rule": True,
        "same_mapping_for_both_variants": GOLD_MAP_VERSION,
        "historical_report_unchanged": True,
        "mapping_fix_is_not_proof_improvement": True,
        "hop_always_is_not_the_contract": True,
        "approved_chain_does_not_upgrade_investigation": True,
        "reference": {"contract": HOP_ALWAYS, **ref_score},
        "treatment": {"contract": CHAIN_CONTRACT, **treat_score},
        "cases": {
            path: {
                "examined_support": (by_id.get(path) or {}).get("examined_support", UNDECIDED),
                "why": (by_id.get(path) or {}).get("why"),
                "navigation": (by_id.get(path) or {}).get("navigation") or [],
                "investigation": INVESTIGATION_PARTIAL,
            }
            for path in (
                "avtal_119.docx",
                "avtal_200.docx",
                "avtal_103.docx",
                "avtal_106.docx",
                "avtal_107.docx",
                "avtal_113.docx",
                "avtal_140.docx",
                "avtal_138.docx",
                "avtal_142.docx",
                "avtal_173.docx",
            )
        },
        "decisions": treatment,
    }


def freeze_decision_contract_baseline(payload: dict[str, object]) -> dict[str, object]:
    reference = payload.get("reference") or {}
    treatment = payload.get("treatment") or {}
    return {
        "id": CHAIN_BASELINE_ID,
        "label": (
            "Frozen: grounded-chain contract versus hop-always, both scored "
            "with gold-map v2. Not applied to v3. Historical reports unchanged."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "does_not_rewrite_history": True,
        "applied_to_v3": False,
        "same_mapping_for_both_variants": GOLD_MAP_VERSION,
        "headline": {
            "mapping": GOLD_MAP_VERSION,
            "mapping_fix_is_not_proof_improvement": True,
            "approved_chain_does_not_upgrade_investigation": True,
            "reference_counts": reference.get("counts") if isinstance(reference, dict) else None,
            "treatment_counts": treatment.get("counts") if isinstance(treatment, dict) else None,
            "treatment_false_approvals": treatment.get("false_approvals")
            if isinstance(treatment, dict)
            else None,
            "treatment_repaired_uncertain": treatment.get("repaired_uncertain")
            if isinstance(treatment, dict)
            else None,
            "cases": payload.get("cases"),
        },
    }


def write_decision_contract_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or CHAIN_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_decision_contract_baseline(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def _gold() -> tuple[RetrievalGold, dict[str, str], dict[str, str]]:
    if not GOLD_ZIP.is_file():
        empty = RetrievalGold(
            id="liability-secrecy-carveout",
            query="",
            relevant_units=[],
            hard_negatives=[],
        )
        return empty, {}, {}
    return load_blind_property("E_sekretessundantag_fran_ansvarsbegransning")


def _passage_grounding(
    traces: list[dict[str, object]],
    gold_spans: list[GoldSpan],
) -> dict[str, object]:
    unique = 0
    for span in gold_spans:
        units = []
        for trace in traces:
            if trace.get("document_id") != span.relative_path:
                continue
            for event in unit_events(trace):
                identity = event.get("identity") if isinstance(event.get("identity"), dict) else {}
                units.append(
                    StoredUnit(
                        node_id=int(identity.get("node_id") or 0),
                        key=str(identity.get("key") or ""),
                        document_id=str(identity.get("document_id") or ""),
                        relative_path=span.relative_path,
                        text=str(event.get("text") or ""),
                        dense=None,
                        sparse=None,
                    )
                )
        mapped = map_span(units, span)
        if mapped["status"] == UNIQUE:
            unique += 1
    return {"gold_quotes": len(gold_spans), "unique_in_examined_chains": unique}
