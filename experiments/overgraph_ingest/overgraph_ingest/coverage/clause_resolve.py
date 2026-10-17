"""Resolve explicit clause citations into the evidence chain. Not a hop-always rule."""

from __future__ import annotations

import re
from dataclasses import dataclass

from overgraph_ingest.coverage.chain_contract import (
    EXCEPTION_RE,
    OSKALIGT_RE,
    SECRECY_RE,
    SUPPORTED,
    UNDECIDED,
    UNHANDLED_AMENDMENT,
    UNRESOLVED_CITATION,
    assess_chain,
    unit_events,
)
from overgraph_ingest.coverage.evidence import validate_span
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL

CLAUSE_CONTRACT = "grounded_chain_with_clause_resolution"
UNIQUE = "unique"
ABSENT = "absent"
AMBIGUOUS = "ambiguous"
RESOLVED_AND_RELATED = "resolved_citation_and_relation"
CITED_CLAUSE_NOT_RELATION = "cited_clause_does_not_support_relation"
AMBIGUOUS_CITATION = "ambiguous_citation"
FINDING_CLAUSE_IS_NOT_ADMISSION = True
CITATION_RE = re.compile(r"(avsnitt|punkt|§)\s*(\d+(?:\.\d+)*)", re.IGNORECASE)
OBJECT_CITATION_RE = re.compile(
    r"(?:brott mot|överträdelse(?:r)? av)(?:\s+\w+ i)?\s+(avsnitt|punkt|§)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
NOTHING_LIMITS_RE = re.compile(
    r"inget i denna (?:punkt|bestämmelse|klausul) ska begränsa",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Citation:
    raw: str
    kind: str
    number: str


@dataclass(frozen=True)
class ClauseUnit:
    relative_path: str
    key: str
    clause_number: str
    title: str
    text: str
    char_start: int | None = None
    char_end: int | None = None
    sequence: int | None = None


@dataclass(frozen=True)
class ClauseLookup:
    citation: Citation
    status: str
    units: tuple[ClauseUnit, ...]


def parse_citations(text: str) -> tuple[Citation, ...]:
    """Citations that are the object of the alleged breach, not every clause number."""
    found = OBJECT_CITATION_RE.finditer(text)
    rows = tuple(
        Citation(match.group(0), match.group(1).casefold(), match.group(2))
        for match in found
    )
    if rows:
        return rows
    return tuple(
        Citation(match.group(0), match.group(1).casefold(), match.group(2))
        for match in CITATION_RE.finditer(text)
    )


def lookup_clause(
    citation: Citation,
    catalog: list[ClauseUnit],
    *,
    relative_path: str,
) -> ClauseLookup:
    matches = [
        unit
        for unit in catalog
        if unit.relative_path == relative_path and _number_matches(citation.number, unit)
    ]
    if not matches:
        return ClauseLookup(citation, ABSENT, ())
    exact = [unit for unit in matches if unit.clause_number == citation.number]
    if len(exact) > 1:
        return ClauseLookup(citation, AMBIGUOUS, tuple(matches))
    prefixes = {unit.clause_number.split(".", 1)[0] for unit in matches if unit.clause_number}
    cited_top = citation.number.split(".", 1)[0]
    if prefixes - {cited_top}:
        return ClauseLookup(citation, AMBIGUOUS, tuple(matches))
    return ClauseLookup(citation, UNIQUE, tuple(matches))


def cited_relation_holds(source_text: str, target_texts: list[str]) -> bool:
    """The cited clause must itself be the secrecy obligation. Finding it is not enough."""
    if OSKALIGT_RE.search(source_text):
        return False
    if not (EXCEPTION_RE.search(source_text) or NOTHING_LIMITS_RE.search(source_text)):
        return False
    return any(SECRECY_RE.search(text) for text in target_texts)


def assess_with_clauses(
    trace: dict[str, object],
    catalog: list[ClauseUnit],
) -> dict[str, object]:
    base = assess_chain(trace)
    path = str(trace.get("document_id") or "")
    lookups = _lookups_for_trace(trace, catalog, path)
    extra_units = _extra_units(trace, lookups)
    searchable = _searchable(trace, decided=base["examined_support"] == SUPPORTED)
    judged = {
        **base,
        "contract": CLAUSE_CONTRACT,
        "lookups": [_lookup_payload(item) for item in lookups],
        "extra_units_fetched": extra_units,
        "finding_clause_is_not_admission": FINDING_CLAUSE_IS_NOT_ADMISSION,
        "undecided_remains_searchable": True,
        "searchable_passages": searchable,
        "approved_chain_does_not_upgrade_investigation": True,
        "investigation": INVESTIGATION_PARTIAL,
    }
    if base["examined_support"] == SUPPORTED:
        return judged
    if base["why"] == UNHANDLED_AMENDMENT:
        return judged
    if base["why"] != UNRESOLVED_CITATION and "resolve_cited_material" not in (
        base.get("navigation") or []
    ):
        return judged
    if not lookups:
        return judged
    if any(item.status == AMBIGUOUS for item in lookups):
        judged.update(examined_support=UNDECIDED, why=AMBIGUOUS_CITATION, evidence_found=False)
        judged["searchable_passages"] = _searchable(trace, decided=False)
        return judged
    if any(item.status != UNIQUE for item in lookups):
        judged.update(examined_support=UNDECIDED, why=UNRESOLVED_CITATION, evidence_found=False)
        judged["searchable_passages"] = _searchable(trace, decided=False)
        return judged
    yes_text = "\n".join(
        str(row.get("text") or "")
        for row in unit_events(trace)
        if row.get("predicted") == "YES"
    )
    targets = [unit.text for item in lookups for unit in item.units]
    if cited_relation_holds(yes_text, targets):
        judged.update(
            examined_support=SUPPORTED,
            why=RESOLVED_AND_RELATED,
            evidence_found=True,
            navigation=[],
        )
        judged["searchable_passages"] = _searchable(trace, decided=True)
        judged["spans"] = list(base.get("spans") or []) + [
            _ground_unit(unit) for item in lookups for unit in item.units
        ]
        return judged
    judged.update(
        examined_support=UNDECIDED,
        why=CITED_CLAUSE_NOT_RELATION,
        evidence_found=False,
        navigation=[],
    )
    judged["searchable_passages"] = _searchable(trace, decided=False)
    return judged


def _lookups_for_trace(
    trace: dict[str, object],
    catalog: list[ClauseUnit],
    path: str,
) -> list[ClauseLookup]:
    seen: set[str] = set()
    rows: list[ClauseLookup] = []
    for event in unit_events(trace):
        if event.get("predicted") != "YES":
            continue
        for citation in parse_citations(str(event.get("text") or "")):
            key = citation.raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append(lookup_clause(citation, catalog, relative_path=path))
    return rows


def _extra_units(trace: dict[str, object], lookups: list[ClauseLookup]) -> int:
    already = {
        str((event.get("identity") or {}).get("key") or "")
        for event in unit_events(trace)
        if isinstance(event.get("identity"), dict)
    }
    fetched = {unit.key for item in lookups for unit in item.units if item.status == UNIQUE}
    return len(fetched - already)


def _searchable(trace: dict[str, object], *, decided: bool) -> list[dict[str, object]]:
    rows = []
    for event in unit_events(trace):
        text = str(event.get("text") or "")
        if not text:
            continue
        identity = event.get("identity") if isinstance(event.get("identity"), dict) else {}
        rows.append(
            {
                "document_id": trace.get("document_id"),
                "unit_key": identity.get("key"),
                "text": text,
                "char_start": identity.get("char_start"),
                "char_end": identity.get("char_end"),
                "prevailing_terms_decided": decided,
            }
        )
    return rows


def _number_matches(reference: str, unit: ClauseUnit) -> bool:
    number = unit.clause_number.strip()
    if number == reference or number.startswith(f"{reference}."):
        return True
    title = unit.title.strip()
    return title.startswith(f"{reference}.") or title.startswith(f"{reference} ")


def _lookup_payload(item: ClauseLookup) -> dict[str, object]:
    return {
        "citation": item.citation.raw,
        "number": item.citation.number,
        "status": item.status,
        "unit_keys": [unit.key for unit in item.units],
        "clause_numbers": [unit.clause_number for unit in item.units],
        "titles": [unit.title for unit in item.units],
    }


def _ground_unit(unit: ClauseUnit) -> dict[str, object]:
    span = validate_span(unit.key, unit.text, unit.text)
    return {
        "unit_id": span.unit_id,
        "start": span.start,
        "end": span.end,
        "text": span.text,
        "validated": span.validated,
        "char_start": unit.char_start,
        "char_end": unit.char_end,
    }


def catalog_from_graph(
    units: list[object],
    structures: dict[str, dict[str, object]],
) -> list[ClauseUnit]:
    rows = []
    for unit in units:
        props = structures.get(getattr(unit, "structure_id", ""), {})
        rows.append(
            ClauseUnit(
                relative_path=str(getattr(unit, "relative_path", "")),
                key=str(getattr(unit, "key", "")),
                clause_number=str(props.get("clause_number") or ""),
                title=str(props.get("title") or ""),
                text=str(getattr(unit, "text", "")),
                char_start=getattr(unit, "char_start", None),
                char_end=getattr(unit, "char_end", None),
                sequence=getattr(unit, "sequence", None),
            )
        )
    return rows
