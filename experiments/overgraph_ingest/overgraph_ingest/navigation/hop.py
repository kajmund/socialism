"""Walk stored OverGraph relations. Does not classify and does not search."""

from __future__ import annotations

import re
from dataclasses import dataclass

from overgraph_ingest.retrieval.index import StoredUnit

PUNKT_RE = re.compile(r"\bpunkt\s+(\d+(?:\.\d+)*)", re.I)
TOP_CLAUSE_HEADING_RE = re.compile(r"^(\d+)\.\s+\S")


@dataclass(frozen=True)
class Hop:
    key: str
    relative_path: str
    relation: str
    text: str
    structure_title: str
    clause_number: str


def section_hops(
    start: StoredUnit,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> list[Hop]:
    same_document = [
        unit
        for unit in units
        if unit.document_id == start.document_id and unit.key != start.key
    ]
    ordered = sorted(same_document + [start], key=lambda item: item.sequence or 0)
    index = next(i for i, unit in enumerate(ordered) if unit.key == start.key)
    related: list[Hop] = []
    if index:
        related.append(_hop(ordered[index - 1], structures, "PREVIOUS"))
    if index + 1 < len(ordered):
        related.append(_hop(ordered[index + 1], structures, "NEXT"))
    start_prefix = _clause_prefix(structures.get(start.structure_id, {}))
    start_parent = str(structures.get(start.structure_id, {}).get("parent_id") or "")
    for unit in same_document:
        if unit.key in {item.key for item in related}:
            continue
        props = structures.get(unit.structure_id, {})
        if unit.structure_id == start.structure_id:
            related.append(_hop(unit, structures, "SAME_STRUCTURE"))
            continue
        if start_parent and str(props.get("parent_id") or "") == start_parent:
            if start_prefix and _clause_prefix(props) == start_prefix:
                related.append(_hop(unit, structures, "SAME_SECTION"))
    return related


HEADING_ONLY_RE = re.compile(r"^\d+(?:\.\d+)*\.\s+\S.{0,80}$")


def is_heading_unit(unit: StoredUnit, structures: dict[str, dict[str, object]]) -> bool:
    text = unit.text.strip()
    if not text:
        return False
    title = str(structures.get(unit.structure_id, {}).get("title") or "").strip()
    if title and (text == title or text.startswith(title) and len(text) <= len(title) + 2):
        return True
    return HEADING_ONLY_RE.match(text) is not None


def child_clause_hops(
    start: StoredUnit,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> list[Hop]:
    start_prefix = _clause_prefix(structures.get(start.structure_id, {}))
    hops: list[Hop] = []
    seen: set[str] = set()
    for unit in units:
        if unit.document_id != start.document_id or unit.key == start.key:
            continue
        props = structures.get(unit.structure_id, {})
        parent = str(props.get("parent_id") or "")
        number = str(props.get("clause_number") or "")
        if parent == start.structure_id or (
            start_prefix and number.startswith(f"{start_prefix}.")
        ):
            if unit.key in seen:
                continue
            seen.add(unit.key)
            hops.append(_hop(unit, structures, "CHILD"))
    return hops


def referenced_clause_hops(
    start: StoredUnit,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> tuple[str | None, list[Hop]]:
    match = PUNKT_RE.search(start.text)
    if match is None:
        return None, []
    reference = match.group(1)
    hops: list[Hop] = []
    for unit in units:
        if unit.document_id != start.document_id or unit.key == start.key:
            continue
        props = structures.get(unit.structure_id, {})
        if _matches_clause_reference(props, reference):
            hops.append(_hop(unit, structures, f"CLAUSE_{reference}"))
    return reference, hops


def _hop(unit: StoredUnit, structures: dict[str, dict[str, object]], relation: str) -> Hop:
    props = structures.get(unit.structure_id, {})
    return Hop(
        key=unit.key,
        relative_path=unit.relative_path,
        relation=relation,
        text=unit.text,
        structure_title=str(props.get("title") or ""),
        clause_number=str(props.get("clause_number") or ""),
    )


def _clause_prefix(props: dict[str, object]) -> str:
    number = str(props.get("clause_number") or "")
    if not number:
        heading = TOP_CLAUSE_HEADING_RE.match(str(props.get("title") or ""))
        number = heading.group(1) if heading else ""
    return number.split(".", 1)[0]


def _is_clause_heading(title: str, number: str) -> bool:
    if not number:
        return False
    if title.startswith(f"{number}. "):
        return True
    return "." in number and title.startswith(f"{number} ")


def _matches_clause_reference(props: dict[str, object], reference: str) -> bool:
    title = str(props.get("title") or "")
    number = str(props.get("clause_number") or "")
    if not _is_clause_heading(title, number):
        return False
    return number == reference or number.startswith(f"{reference}.")
