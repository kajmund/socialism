"""Replay why hop-always marked EVIDENCE_FOUND. No new Jev or embeddings."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.cache import load_c8_judgments
from overgraph_ingest.coverage.controller import SECTION_HOP_RELATIONS
from overgraph_ingest.coverage.proof_gate import admit_complete, polarity_status
from overgraph_ingest.coverage.proof_link import evaluate_passage
from overgraph_ingest.coverage.state import (
    EVIDENCE_FOUND,
    DocumentState,
    UnitRecord,
    resolve_status,
)
from overgraph_ingest.coverage.v2 import DEFAULT_CACHE
from overgraph_ingest.graph.writer import GraphWriter, open_database
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.navigation.hop import section_hops
from overgraph_ingest.retrieval.gold import load_retrieval_gold

ROOT = Path(__file__).resolve().parents[2]
FOUND_BASELINE_ID = "phase2-proof-found-v1"
FOUND_BASELINE_PATH = ROOT / "baselines" / f"{FOUND_BASELINE_ID}.json"
DEFAULT_DB = ROOT / "data" / "extra-overgraph-phase2"
DEFAULT_GOLD = ROOT / "retrieval_gold" / "liability-secrecy-carveout.json"
DEFAULT_V3 = ROOT / "data" / "coverage-v3.json"
DEFAULT_GATE = ROOT / "data" / "coverage-v3-gate-carveout.json"
TARGET_PATHS = (
    "Avtal_12_Uppsagningsbesked_overenskommelse_avslut.docx",
    "Avtal_60_Pilotavtal_PoC.docx",
)


def run_proof_found(
    *,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    gold_path: Path | None = None,
    v3_path: Path | None = None,
    gate_path: Path | None = None,
) -> dict[str, object]:
    gold = load_retrieval_gold(gold_path or DEFAULT_GOLD)
    c8 = load_c8_judgments(json.loads((ROOT / DEFAULT_CACHE[gold.id]).read_text(encoding="utf-8")))
    v3 = _gold_row(json.loads((v3_path or DEFAULT_V3).read_text(encoding="utf-8")), gold.id)
    gate = _gold_row(json.loads((gate_path or DEFAULT_GATE).read_text(encoding="utf-8")), gold.id)
    db = open_database(db_path or DEFAULT_DB, dense_dimension)
    try:
        context = load_graph_context(GraphWriter(db, batch_size=500))
    finally:
        db.close()
    cases = [
        reconstruct_document(
            path,
            units=[unit for unit in context.units if unit.relative_path == path],
            context=context,
            c8=c8,
            gold_relevant=path in gold.relevant_documents,
            v3=v3,
            gate=gate,
        )
        for path in TARGET_PATHS
    ]
    return {
        "operation": "coverage",
        "experiment": "proof_found_v1",
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "classify_unchanged": True,
        "no_new_jev": True,
        "no_new_embeddings": True,
        "controller_unchanged": True,
        "hop_always_contract": (
            "COMPOSITE EVIDENCE_FOUND after a YES and hop_attempted, "
            "or required_parts. No evidence span is stored."
        ),
        "cases": cases,
    }


def reconstruct_document(
    path: str,
    *,
    units,
    context,
    c8: list[dict[str, object]],
    gold_relevant: bool,
    v3: dict[str, object],
    gate: dict[str, object],
) -> dict[str, object]:
    by_path = [row for row in c8 if row.get("relative_path") == path]
    first_yes = next((row for row in by_path if row.get("predicted") == "YES"), None)
    yes_source = "c8"
    if first_yes is None:
        hypothesized = [
            unit for unit in units if _mentions_proof(unit.text)
        ]
        if len(hypothesized) == 1:
            first_yes = {
                "key": hypothesized[0].key,
                "rank": None,
                "predicted": "YES",
                "text": hypothesized[0].text,
            }
            yes_source = "only_candidate_unit"
    yes_unit = None if first_yes is None else _unit_by_key(units, str(first_yes.get("key") or ""))
    hops = []
    if yes_unit is not None:
        hops = [
            {
                "relation": hop.relation,
                "key": hop.key,
                "text": _unit_by_key(units, hop.key).text if _unit_by_key(units, hop.key) else "",
            }
            for hop in section_hops(yes_unit, context.units, context.structures)
            if hop.relation in SECTION_HOP_RELATIONS
        ]
    reconstructed = _reconstruct_state(path, units, first_yes, hops)
    hop_always = resolve_status(reconstructed, proof_kind="COMPOSITE")
    gated = resolve_status(reconstructed, proof_kind="COMPOSITE", proof_gate=True)
    yes_text = "" if first_yes is None else str(first_yes.get("text") or "")
    passage = evaluate_passage(yes_text) if yes_text else None
    admission = admit_complete(
        yes_texts=[yes_text] if yes_text else [],
        hop_pairs=[
            (yes_text, str(hop["text"]))
            for hop in hops
            if hop.get("text")
        ],
    )
    return {
        "relative_path": path,
        "gold_relevant": gold_relevant,
        "unit_count": len(units),
        "c8_judgments": [
            {
                "key": row.get("key"),
                "rank": row.get("rank"),
                "predicted": row.get("predicted"),
                "text": row.get("text"),
            }
            for row in by_path
        ],
        "first_yes": None
        if first_yes is None
        else {
            "key": first_yes.get("key"),
            "rank": first_yes.get("rank"),
            "source": yes_source,
            "hypothesized": yes_source != "c8",
            "text": first_yes.get("text"),
        },
        "explicit_relations_in_yes": None
        if passage is None
        else {
            "link_status": passage["status"],
            "linked_span": passage.get("linked_span"),
            "reference": passage.get("reference"),
            "polarity": polarity_status(yes_text),
        },
        "hop_targets_from_yes": hops,
        "final_rule": {
            "hop_always": hop_always,
            "with_gate": gated,
            "gate_reason": None if reconstructed.gate_block is None else reconstructed.gate_block.get("reason"),
            "requires_evidence_span": False,
            "completes_because": _because(hop_always, first_yes, hops),
        },
        "evidence_span": {
            "showable": hop_always == EVIDENCE_FOUND and bool(yes_text) and passage is not None and passage["status"] == "linked_relation",
            "yes_text": yes_text or None,
            "used_for_complete": "yes_count and hop_attempted" if hop_always == EVIDENCE_FOUND else None,
            "used_for_gate": admission,
        },
        "observed_v3": _observed(v3, path, gold_relevant, extra_path=TARGET_PATHS[0]),
        "observed_gate": _observed(gate, path, gold_relevant),
        "candidate_units": [
            {
                "key": unit.key,
                "sequence": unit.sequence,
                "text": unit.text,
                "in_c8": any(row.get("key") == unit.key for row in by_path),
            }
            for unit in sorted(units, key=lambda item: (item.sequence is None, item.sequence or 0))
            if _mentions_proof(unit.text)
        ],
    }


def freeze_proof_found_baseline(payload: dict[str, object]) -> dict[str, object]:
    cases = {row["relative_path"]: row for row in payload.get("cases") or []}
    avtal_12 = cases.get(TARGET_PATHS[0]) or {}
    avtal_60 = cases.get(TARGET_PATHS[1]) or {}
    return {
        "id": FOUND_BASELINE_ID,
        "label": (
            "Frozen: hop-always EVIDENCE_FOUND has no evidence span. "
            "Replay of Avtal 12 and Avtal 60. Not a new controller."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "classify_unchanged": True,
        "no_new_jev": True,
        "headline": {
            "hop_always_requires_evidence_span": False,
            "avtal_12_first_yes_in_c8": (
                (avtal_12.get("first_yes") or {}).get("source") == "c8"
            ),
            "avtal_12_hypothesized_yes": (avtal_12.get("first_yes") or {}).get("hypothesized"),
            "avtal_12_hop_always": (avtal_12.get("final_rule") or {}).get("hop_always"),
            "avtal_60_first_yes_in_c8": avtal_60.get("first_yes") is not None,
            "avtal_60_link_status": ((avtal_60.get("explicit_relations_in_yes") or {}).get("link_status")),
            "avtal_60_polarity": ((avtal_60.get("explicit_relations_in_yes") or {}).get("polarity")),
            "avtal_60_gate": (avtal_60.get("final_rule") or {}).get("with_gate"),
        },
        "cases": payload.get("cases"),
    }


def write_proof_found_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or FOUND_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_proof_found_baseline(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def load_proof_found_baseline(path: Path | None = None) -> dict[str, object]:
    return json.loads((path or FOUND_BASELINE_PATH).read_text(encoding="utf-8"))


def _reconstruct_state(path, units, first_yes, hops) -> DocumentState:
    retrieved: list[UnitRecord] = []
    if first_yes is not None:
        retrieved.append(
            UnitRecord(
                key=str(first_yes.get("key") or "yes"),
                predicted="YES",
                source="c8",
                text=str(first_yes.get("text") or ""),
            )
        )
        if hops:
            hop = hops[0]
            retrieved.append(
                UnitRecord(
                    key=str(hop["key"]),
                    predicted="NO",
                    source="hop",
                    hop=f"hop:{hop['relation']}",
                    text=str(hop.get("text") or ""),
                )
            )
    return DocumentState(
        relative_path=path,
        document_units=max(len(units), 1),
        retrieved=retrieved,
        hop_attempted=bool(hops),
    )


def _because(status: str, first_yes, hops) -> str | None:
    if status != EVIDENCE_FOUND:
        return None
    if first_yes is not None and hops:
        return "yes_and_hop_attempted"
    if first_yes is not None:
        return "yes_count"
    return None


def _observed(
    gold_row: dict[str, object],
    path: str,
    relevant: bool,
    extra_path: str | None = None,
) -> dict[str, object]:
    rows = []
    for budget in gold_row.get("budgets") or []:
        leftover = budget.get("unresolved_relevant_documents") or []
        extra = list(budget.get("evidence_found_nonrelevant") or [])
        counts = budget.get("status_counts") or {}
        found = int(counts.get("EVIDENCE_FOUND") or 0)
        expected = int(budget.get("documents_expected") or 7)
        if not extra and extra_path and found > expected:
            extra = [extra_path]
        undecided = budget.get("gate_undecided") or []
        if relevant:
            complete = path not in leftover
        else:
            complete = path in extra
        rows.append(
            {
                "budget": budget.get("budget"),
                "complete": complete,
                "undecided": path in undecided,
                "classified": budget.get("classified"),
            }
        )
    first = next((row for row in rows if row["complete"]), None)
    return {
        "first_complete_budget": None if first is None else first["budget"],
        "first_complete_classified": None if first is None else first["classified"],
        "budgets": rows,
    }


def _mentions_proof(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in ("ansvar", "sekretess", "begräns", "utom", "företagsheml"))


def _unit_by_key(units, key: str):
    return next((unit for unit in units if unit.key == key), None)


def _gold_row(payload: dict[str, object], gold_id: str) -> dict[str, object]:
    for item in payload.get("golds") or []:
        if item.get("gold_id") == gold_id:
            return dict(item)
    return {}
