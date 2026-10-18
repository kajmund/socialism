"""Recognize artikel, klausul, and roman citations. Do not change the relation test."""

from __future__ import annotations

import re

from overgraph_ingest.coverage.anaphor_resolve import assess_with_anaphors
from overgraph_ingest.coverage.chain_contract import (
    OSKALIGT_NOT_CLAIM,
    SUPPORTED,
    UNDECIDED,
    UNHANDLED_AMENDMENT,
    unit_events,
)
from overgraph_ingest.coverage.citation_parse import is_label_form, parse_object_labels
from overgraph_ingest.coverage.clause_resolve import (
    AMBIGUOUS,
    AMBIGUOUS_CITATION,
    ABSENT,
    CITED_CLAUSE_NOT_RELATION,
    Citation,
    ClauseLookup,
    ClauseUnit,
    RESOLVED_AND_RELATED,
    UNIQUE,
    UNRESOLVED_CITATION,
    _number_matches,
    cited_relation_holds,
)
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL

LABEL_CONTRACT = "grounded_chain_with_citation_labels"
LEAVE_UNCHANGED = {UNHANDLED_AMENDMENT, OSKALIGT_NOT_CLAIM, "oskaligt_is_not_the_claim"}
ARTIKEL_TITLE_RE = re.compile(r"^artikel\s+", re.IGNORECASE)
SECTION_SIGN_RE = re.compile(r"^§\s*")


def assess_with_citation_labels(trace: dict[str, object], catalog: list) -> dict[str, object]:
    base = assess_with_anaphors(trace, catalog)
    judged = {
        **base,
        "contract": LABEL_CONTRACT,
        "finding_clause_is_not_admission": True,
        "does_not_change_relation_test": True,
        "artikel_is_not_section_alias": True,
        "roman_is_not_arabic_alias": True,
        "investigation": INVESTIGATION_PARTIAL,
        "approved_chain_does_not_upgrade_investigation": True,
    }
    if base.get("examined_support") == SUPPORTED:
        return judged
    if base.get("why") in LEAVE_UNCHANGED:
        return judged
    lookups = _lookups_for_trace(trace, catalog)
    judged["label_lookups"] = [_lookup_payload(item) for item in lookups]
    extra = _extra_units(trace, lookups)
    judged["extra_units_fetched"] = int(base.get("extra_units_fetched") or 0) + extra
    if not lookups:
        return judged
    if any(item.status == AMBIGUOUS for item in lookups):
        judged.update(examined_support=UNDECIDED, why=AMBIGUOUS_CITATION, evidence_found=False)
        return judged
    if any(item.status != UNIQUE for item in lookups):
        judged.update(examined_support=UNDECIDED, why=UNRESOLVED_CITATION, evidence_found=False)
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
        return judged
    judged.update(
        examined_support=UNDECIDED,
        why=CITED_CLAUSE_NOT_RELATION,
        evidence_found=False,
    )
    return judged


def lookup_labeled_clause(
    citation: Citation,
    catalog: list[ClauseUnit],
    *,
    relative_path: str,
) -> ClauseLookup:
    matches = [
        unit
        for unit in catalog
        if unit.relative_path == relative_path and labeled_number_matches(citation, unit)
    ]
    if not matches:
        return ClauseLookup(citation, ABSENT, ())
    exact = [
        unit
        for unit in matches
        if unit.clause_number == citation.number or _title_is_kind_number(citation, unit)
    ]
    if len(exact) > 1 and citation.kind != "artikel":
        return ClauseLookup(citation, AMBIGUOUS, tuple(matches))
    prefixes = {unit.clause_number.split(".", 1)[0] for unit in matches if unit.clause_number}
    cited_top = citation.number.split(".", 1)[0]
    if prefixes - {cited_top}:
        return ClauseLookup(citation, AMBIGUOUS, tuple(matches))
    return ClauseLookup(citation, UNIQUE, tuple(matches))


def labeled_number_matches(citation: Citation, unit: ClauseUnit) -> bool:
    title = _title(unit)
    if citation.kind == "artikel":
        if re.match(rf"^artikel\s+{re.escape(citation.number)}\b", title, re.I):
            return True
        if SECTION_SIGN_RE.match(title):
            return False
        number = unit.clause_number.strip()
        return number.startswith(f"{citation.number}.")
    if citation.kind == "§":
        return bool(re.match(rf"^§\s*{re.escape(citation.number)}\b", title))
    if SECTION_SIGN_RE.match(title) or ARTIKEL_TITLE_RE.match(title):
        return False
    return _number_matches(citation.number, unit)


def kind_accepts(citation: Citation, unit: ClauseUnit) -> bool:
    return labeled_number_matches(citation, unit)


def _title(unit: ClauseUnit) -> str:
    text = unit.title or unit.text
    return text.strip().splitlines()[0] if text else ""


def _title_is_kind_number(citation: Citation, unit: ClauseUnit) -> bool:
    title = _title(unit)
    if citation.kind == "artikel":
        return bool(re.match(rf"^artikel\s+{re.escape(citation.number)}\b", title, re.I))
    if citation.kind == "§":
        return bool(re.match(rf"^§\s*{re.escape(citation.number)}\b", title))
    return False


def _lookups_for_trace(
    trace: dict[str, object],
    catalog: list,
    path: str | None = None,
) -> list[ClauseLookup]:
    document = path or str(trace.get("document_id") or "")
    seen: set[str] = set()
    rows: list[ClauseLookup] = []
    for event in unit_events(trace):
        if event.get("predicted") != "YES":
            continue
        for citation in parse_object_labels(str(event.get("text") or "")):
            if not is_label_form(citation):
                continue
            key = citation.raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append(lookup_labeled_clause(citation, catalog, relative_path=document))
    return rows


def _extra_units(trace: dict[str, object], lookups: list[ClauseLookup]) -> int:
    already = {
        str((event.get("identity") or {}).get("key") or "")
        for event in unit_events(trace)
        if isinstance(event.get("identity"), dict)
    }
    fetched = {unit.key for item in lookups for unit in item.units if item.status == UNIQUE}
    return len(fetched - already)


def _lookup_payload(item: ClauseLookup) -> dict[str, object]:
    return {
        "citation": item.citation.raw,
        "kind": item.citation.kind,
        "number": item.citation.number,
        "status": item.status,
        "unit_keys": [unit.key for unit in item.units],
        "clause_numbers": [unit.clause_number for unit in item.units],
        "titles": [unit.title for unit in item.units],
    }
