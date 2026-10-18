"""Search representations for TextUnits. Evidence text stays original."""

from __future__ import annotations

from collections import defaultdict

from overgraph_ingest.retrieval.index import StoredUnit

ORIGINAL = "A"
STRUCTURE = "B"
LOCAL = "C"
REPRESENTATIONS = (ORIGINAL, STRUCTURE, LOCAL)
FIRST_RUN = (ORIGINAL, STRUCTURE)
HEADING_JOIN = " → "


def heading_titles(structure: dict[str, object]) -> tuple[str, ...]:
    path = str(structure.get("path") or "")
    titles: list[str] = []
    for part in path.split("/"):
        if not part:
            continue
        _ordinal, separator, title = part.partition(":")
        titles.append(title if separator else part)
    if titles:
        return tuple(titles)
    title = str(structure.get("title") or "").strip()
    return (title,) if title else ()


def units_by_document(units: list[StoredUnit]) -> dict[str, list[StoredUnit]]:
    grouped: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        grouped[unit.document_id].append(unit)
    return {
        document_id: sorted(group, key=lambda item: item.sequence or 0)
        for document_id, group in grouped.items()
    }


def previous_sibling_text(
    unit: StoredUnit,
    ordered: list[StoredUnit],
) -> str:
    for index, item in enumerate(ordered):
        if item.key != unit.key:
            continue
        if index == 0:
            return ""
        previous = ordered[index - 1]
        if previous.structure_id != unit.structure_id:
            return ""
        return previous.text
    raise KeyError(unit.key)


def search_text(
    representation: str,
    unit: StoredUnit,
    *,
    structures: dict[str, dict[str, object]],
    ordered: list[StoredUnit],
) -> str:
    evidence = unit.text
    if representation == ORIGINAL:
        return evidence
    titles = heading_titles(structures.get(unit.structure_id, {}))
    if representation == STRUCTURE:
        return _with_headings(evidence, titles)
    if representation == LOCAL:
        previous = previous_sibling_text(unit, ordered)
        return _with_local(evidence, titles, previous)
    raise ValueError(f"unknown representation: {representation}")


def search_texts(
    representation: str,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> dict[str, str]:
    grouped = units_by_document(units)
    by_key = {unit.key: unit for unit in units}
    return {
        key: search_text(
            representation,
            unit,
            structures=structures,
            ordered=grouped[unit.document_id],
        )
        for key, unit in by_key.items()
    }


def _with_headings(evidence: str, titles: tuple[str, ...]) -> str:
    if not titles:
        return evidence
    return f"{HEADING_JOIN.join(titles)}\n{evidence}"


def _with_local(evidence: str, titles: tuple[str, ...], previous: str) -> str:
    parts = []
    if titles:
        parts.append(HEADING_JOIN.join(titles))
    if previous:
        parts.append(previous)
    parts.append(evidence)
    return "\n".join(parts)
