"""Two measured hops. Classify is unchanged; this only fetches missing evidence."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.graph.schema import STRUCTURE
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.navigation.hop import Hop, referenced_clause_hops, section_hops
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units

AVTAL_46 = "Avtal_46_SaaS_avtal.docx"
AVTAL_49 = "Avtal_49_IT_drift_hostingavtal.docx"
AVTAL_46_START = "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot sekretess."
AVTAL_46_TARGET = (
    "DevBrains sammanlagda ansvar per avtalsår är begränsat till de avgifter "
    "som Kunden har betalat under de senaste tolv (12) månaderna."
)
AVTAL_49_START = "Begränsningarna gäller inte vid uppsåt, grov vårdslöshet eller brott mot punkt 4."
AVTAL_49_TARGET_TITLE = "4. Informationssäkerhet och dataskydd"


@dataclass
class NavigationReport:
    payload: dict[str, object]


def run_navigation(*, db_path: Path, dense_dimension: int | None) -> NavigationReport:
    dimension = resolve_dimension(db_path, dense_dimension)
    db = open_database(db_path, dimension)
    started = time.perf_counter()
    try:
        writer = GraphWriter(db, batch_size=500)
        units = load_published_units(writer)
        structures = _structures(writer)
        cases = [
            _avtal_46(units, structures),
            _avtal_49(units, structures),
        ]
        payload = {
            "operation": "navigate",
            "classify_unchanged": True,
            "cases": cases,
            "wall_seconds": time.perf_counter() - started,
        }
    finally:
        db.close()
    return NavigationReport(payload=payload)


def _avtal_46(
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> dict[str, object]:
    start = _require_unit(units, AVTAL_46, AVTAL_46_START)
    hops = section_hops(start, units, structures)
    found = [hop for hop in hops if AVTAL_46_TARGET in hop.text]
    wrong = [
        hop
        for hop in hops
        if AVTAL_46_TARGET not in hop.text and not hop.clause_number.startswith("12")
    ]
    payload = _case_payload(
        case_id="avtal-46-section",
        start=start,
        hops=hops,
        found=found,
        target="liability cap in the same ansvar section",
        extra_note=(
            "A PREVIOUS/SAME_SECTION hop can fetch the missing cap. "
            "Do not relabel the carve-out unit from the cap."
        ),
    )
    payload["wrong_hops"] = len(wrong)
    return payload


def _avtal_49(
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> dict[str, object]:
    start = _require_unit(units, AVTAL_49, AVTAL_49_START)
    reference, hops = referenced_clause_hops(start, units, structures)
    found = [
        hop
        for hop in hops
        if hop.structure_title.startswith(AVTAL_49_TARGET_TITLE)
        or hop.clause_number == reference
        or hop.clause_number.startswith(f"{reference}.")
    ]
    secrecy = [hop for hop in found if "sekretess" in hop.text.lower()]
    return _case_payload(
        case_id="avtal-49-punkt-4",
        start=start,
        hops=hops,
        found=found,
        target="clause 4 Informationssäkerhet och dataskydd",
        extra_note=(
            "Punkt 4 is information security and data protection, not sekretess. "
            "Isolated classify on 6.3 should stay UNCERTAIN; assembly can now "
            "source a document-level NO for the secrecy-carve-out question."
        ),
        extra={
            "reference": reference,
            "referenced_title": next(
                (hop.structure_title for hop in hops if hop.clause_number == reference),
                "",
            ),
            "mentions_sekretess": len(secrecy),
            "needs_evidence_assembly": True,
        },
    )


def _case_payload(
    *,
    case_id: str,
    start: StoredUnit,
    hops: list[Hop],
    found: list[Hop],
    target: str,
    extra_note: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    relations = {hop.relation for hop in hops}
    payload = {
        "id": case_id,
        "start_path": start.relative_path,
        "start_key": start.key,
        "target": target,
        "navigation_recall": 1.0 if found else 0.0,
        "extra_text_units": len(hops),
        "extra_jev_calls": 0,
        "wrong_hops": max(0, len(hops) - len(found)),
        "relations_used": sorted(relations),
        "found": [_hop_row(hop) for hop in found],
        "fetched": [_hop_row(hop) for hop in hops],
        "note": extra_note,
    }
    if extra:
        payload.update(extra)
    return payload


def _hop_row(hop: Hop) -> dict[str, object]:
    return {
        "key": hop.key,
        "relative_path": hop.relative_path,
        "relation": hop.relation,
        "clause_number": hop.clause_number,
        "structure_title": hop.structure_title,
        "text": hop.text[:240],
    }


def _require_unit(units: list[StoredUnit], relative_path: str, snippet: str) -> StoredUnit:
    for unit in units:
        if unit.relative_path == relative_path and snippet in unit.text:
            return unit
    raise KeyError(f"missing start unit {relative_path}: {snippet}")


def _structures(writer: GraphWriter) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for node in writer.iter_nodes(STRUCTURE):
        rows[str(node.key)] = dict(node.props)
    return rows
