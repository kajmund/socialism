"""Anchor anaphors and list items to a predication. Do not concatenate units."""

from __future__ import annotations

import re

from overgraph_ingest.coverage.chain_contract import (
    ANAPHOR_RE,
    EXCEPTION_RE,
    LIST_RE,
    OSKALIGT_NOT_CLAIM,
    OSKALIGT_RE,
    SECRECY_RE,
    SUPPORTED,
    UNDECIDED,
    UNHANDLED_AMENDMENT,
    UNRESOLVED_CITATION,
    unit_events,
)
from overgraph_ingest.coverage.clause_resolve import (
    AMBIGUOUS_CITATION,
    CITED_CLAUSE_NOT_RELATION,
    NOTHING_LIMITS_RE,
    assess_with_clauses,
)
from overgraph_ingest.coverage.proof_logic import split_predications
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL

ANAPHOR_CONTRACT = "grounded_chain_with_anaphor_list"
RESOLVED_ANAPHOR = "resolved_anaphor"
RESOLVED_LIST = "resolved_list"
ANAPHOR_ANTECEDENT_NOT_EXCEPTION = "anaphor_antecedent_is_not_exception"
ANAPHOR_MISSING_ANTECEDENT = "anaphor_antecedent_absent"
FINDING_ANTECEDENT_IS_NOT_ADMISSION = True
ITEM_RE = re.compile(r"\(([a-z]|\d+)\)\s*")
LEAVE_UNCHANGED = {
    UNHANDLED_AMENDMENT,
    UNRESOLVED_CITATION,
    CITED_CLAUSE_NOT_RELATION,
    AMBIGUOUS_CITATION,
    OSKALIGT_NOT_CLAIM,
    "oskaligt_is_not_the_claim",
}


def assess_with_anaphors(trace: dict[str, object], catalog: list) -> dict[str, object]:
    base = assess_with_clauses(trace, catalog)
    judged = {
        **base,
        "contract": ANAPHOR_CONTRACT,
        "finding_antecedent_is_not_admission": FINDING_ANTECEDENT_IS_NOT_ADMISSION,
        "does_not_concatenate_units": True,
        "investigation": INVESTIGATION_PARTIAL,
        "approved_chain_does_not_upgrade_investigation": True,
    }
    link = _first_link(trace, catalog)
    judged["discourse_link"] = link
    extra = int(link.get("extra_units") or 0) if link else 0
    judged["extra_units_fetched"] = int(base.get("extra_units_fetched") or 0) + extra
    if not link:
        return judged
    if base.get("why") in LEAVE_UNCHANGED:
        return judged
    if link["kind"] == "list" and link["holds"]:
        judged.update(examined_support=SUPPORTED, why=RESOLVED_LIST, evidence_found=True, navigation=[])
        return judged
    if link["kind"] == "anaphor" and link["holds"]:
        judged.update(examined_support=SUPPORTED, why=RESOLVED_ANAPHOR, evidence_found=True, navigation=[])
        return judged
    if base.get("examined_support") == SUPPORTED:
        return judged
    judged.update(
        examined_support=UNDECIDED,
        why=str(link.get("why") or ANAPHOR_MISSING_ANTECEDENT),
        evidence_found=False,
    )
    return judged


def anaphor_relation_holds(antecedent: str, anaphor: str) -> bool:
    if OSKALIGT_RE.search(antecedent) or OSKALIGT_RE.search(anaphor):
        return False
    if not _is_exception(antecedent):
        return False
    return bool(SECRECY_RE.search(anaphor))


def list_relation_holds(intro: str, items: list[str]) -> bool:
    if OSKALIGT_RE.search(intro) or not LIST_RE.search(intro):
        return False
    return any(SECRECY_RE.search(item) for item in items)


def _first_link(trace: dict[str, object], catalog: list) -> dict[str, object] | None:
    path = str(trace.get("document_id") or "")
    events = unit_events(trace)
    for event in events:
        if event.get("predicted") != "YES":
            continue
        text = str(event.get("text") or "")
        listed = _list_link(text)
        if listed is not None:
            return listed
        anaphor = _anaphor_link(event, events, catalog, path)
        if anaphor is not None:
            return anaphor
    return None


def _list_link(text: str) -> dict[str, object] | None:
    if not LIST_RE.search(text):
        return None
    parts = ITEM_RE.split(text)
    intro = parts[0] if parts else text
    items = [part.strip() for part in parts[1:] if part.strip() and not re.fullmatch(r"[a-z]|\d+", part)]
    if not items and ITEM_RE.search(text):
        items = [chunk.strip() for chunk in ITEM_RE.split(text)[1:] if len(chunk.strip()) > 1]
    holds = list_relation_holds(intro, items)
    return {
        "kind": "list",
        "how": "list_intro_to_item",
        "intro": intro.strip(),
        "items": items,
        "holds": holds,
        "extra_units": 0,
        "why": None if holds else "list_item_is_not_secrecy_exception",
    }


def _anaphor_link(
    yes_event: dict[str, object],
    events: list[dict[str, object]],
    catalog: list,
    path: str,
) -> dict[str, object] | None:
    text = str(yes_event.get("text") or "")
    predications = list(split_predications(text))
    for index, predication in enumerate(predications):
        if not ANAPHOR_RE.search(predication):
            continue
        if index > 0:
            antecedent = predications[index - 1]
            extra = 0
            how = "previous_sentence_in_unit"
        else:
            previous, extra = _previous_predication(yes_event, events, catalog, path)
            if previous is None:
                return {
                    "kind": "anaphor",
                    "how": "absent",
                    "anaphor": predication,
                    "antecedent": None,
                    "holds": False,
                    "extra_units": extra,
                    "why": ANAPHOR_MISSING_ANTECEDENT,
                }
            antecedent = previous
            how = "previous_unit_predication"
        holds = anaphor_relation_holds(antecedent, predication)
        return {
            "kind": "anaphor",
            "how": how,
            "anaphor": predication,
            "antecedent": antecedent,
            "holds": holds,
            "extra_units": extra,
            "why": None if holds else ANAPHOR_ANTECEDENT_NOT_EXCEPTION,
        }
    return None


def _previous_predication(
    yes_event: dict[str, object],
    events: list[dict[str, object]],
    catalog: list,
    path: str,
) -> tuple[str | None, int]:
    sequence = _sequence(yes_event)
    if sequence is not None:
        for event in events:
            if _sequence(event) == sequence - 1:
                return _last_predication(str(event.get("text") or "")), 0
        for unit in catalog:
            if getattr(unit, "relative_path", "") != path:
                continue
            if getattr(unit, "sequence", None) == sequence - 1:
                already = {
                    str((event.get("identity") or {}).get("key") or "")
                    for event in events
                    if isinstance(event.get("identity"), dict)
                }
                extra = 0 if unit.key in already else 1
                return _last_predication(unit.text), extra
    for event in events:
        hop = str(event.get("hop") or event.get("source") or "")
        if "PREVIOUS" in hop:
            return _last_predication(str(event.get("text") or "")), 0
    return None, 0


def _last_predication(text: str) -> str:
    parts = split_predications(text)
    return parts[-1] if parts else text


def _is_exception(text: str) -> bool:
    return bool(EXCEPTION_RE.search(text) or NOTHING_LIMITS_RE.search(text))


def _sequence(event: dict[str, object]) -> int | None:
    identity = event.get("identity") if isinstance(event.get("identity"), dict) else {}
    value = identity.get("sequence")
    return int(value) if value is not None else None
