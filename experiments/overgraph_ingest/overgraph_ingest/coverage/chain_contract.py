"""Grounded-chain decision contract. Replaces YES+hop. Not Coverage v3."""

from __future__ import annotations

import re

from overgraph_ingest.coverage.evidence import CLAIM, validate_span
from overgraph_ingest.coverage.stop_replay import INVESTIGATION_PARTIAL

SUPPORTED = "SUPPORTED"
UNDECIDED = "UNDECIDED"
HOP_ALWAYS = "yes_plus_hop"
CHAIN_CONTRACT = "grounded_chain"
EXISTING_LINK = "existing_link_in_unit"
RESOLVED_CITATION = "resolved_citation"
RESOLVED_HEADING = "resolved_heading"
UNRESOLVED_CITATION = "unresolved_citation"
UNRESOLVED_ANAPHOR = "unresolved_anaphor"
UNHANDLED_AMENDMENT = "unhandled_examined_amendment"
OSKALIGT_NOT_CLAIM = "oskaligt_is_not_the_claim"
HOP_IS_NOT_ADMISSION = "hop_is_not_admission"
MISSING_SUPPORT = "no_grounded_supporting_text"

CITATION_RE = re.compile(r"(?:avsnitt|punkt|§)\s*\d+(?:\.\d+)*", re.IGNORECASE)
HEADING_RE = re.compile(r"rubriken\s+[\"“”«»']([^\"“”«»']+)", re.IGNORECASE)
AMENDMENT_RE = re.compile(r"med ändring av|med avvikelse från", re.IGNORECASE)
ANAPHOR_RE = re.compile(r"\b(?:detsamma gäller|samma sak gäller)\b", re.IGNORECASE)
EXCEPTION_RE = re.compile(
    r"(?:gäller inte|inte tillämplig|ska inte tillämpas|är inte tillämplig|ska inte begränsa)",
    re.IGNORECASE,
)
LIST_RE = re.compile(r"gäller inte i följande fall", re.IGNORECASE)
SECRECY_RE = re.compile(
    r"(?:sekretess|tystnadsplikt|konfidentiell information|förtrolig information)",
    re.IGNORECASE,
)
OSKALIGT_RE = re.compile(r"oskälig", re.IGNORECASE)


def unit_events(trace: dict[str, object]) -> list[dict[str, object]]:
    return [
        event
        for event in (trace.get("events") or [])
        if isinstance(event, dict) and event.get("kind") in {"classify", "navigation"}
    ]


def assess_chain(trace: dict[str, object]) -> dict[str, object]:
    """Candidate units → grounded chain → proof requirements. Hop is not admission."""
    units = unit_events(trace)
    yes_rows = [row for row in units if row.get("predicted") == "YES"]
    spans = [_ground(row) for row in yes_rows]
    supporting = bool(spans) and all(span["validated"] for span in spans)
    uncertain = any(row.get("predicted") == "UNCERTAIN" for row in units)
    amendments = [row for row in units if AMENDMENT_RE.search(str(row.get("text") or ""))]
    hop_attempted = any(row.get("kind") == "navigation" for row in units)
    others = [str(row.get("text") or "") for row in units if row.get("predicted") != "YES"]
    link = _link(yes_rows, others)
    amendment_answered = not amendments
    if uncertain:
        status = UNDECIDED
        why = "do_not_repair_uncertain"
    elif not supporting:
        status = UNDECIDED
        why = MISSING_SUPPORT
    elif not amendment_answered:
        status = UNDECIDED
        why = UNHANDLED_AMENDMENT
    elif link["answered"]:
        status = SUPPORTED
        why = str(link["how"])
    else:
        status = UNDECIDED
        why = str(link["how"] or HOP_IS_NOT_ADMISSION)
    navigation = [] if status == SUPPORTED else list(link["navigation"])
    if not amendment_answered:
        navigation = ["account_for_examined_amendment", *navigation]
    return {
        "document_id": trace.get("document_id"),
        "contract": CHAIN_CONTRACT,
        "examined_support": status,
        "investigation": INVESTIGATION_PARTIAL,
        "approved_chain_does_not_upgrade_investigation": True,
        "hop_attempted": hop_attempted,
        "hop_is_not_admission": True,
        "why": why,
        "requirements": {
            "supporting_text": supporting,
            "link": link,
            "amendment_handled": amendment_answered,
        },
        "navigation": navigation,
        "spans": spans,
        "claim": CLAIM,
        "evidence_found": status == SUPPORTED,
    }


def hop_always_decision(trace: dict[str, object]) -> dict[str, object]:
    found = trace.get("status") == "EVIDENCE_FOUND" or bool(trace.get("why_evidence_found"))
    return {
        "document_id": trace.get("document_id"),
        "contract": HOP_ALWAYS,
        "examined_support": SUPPORTED if found else UNDECIDED,
        "investigation": INVESTIGATION_PARTIAL,
        "approved_chain_does_not_upgrade_investigation": True,
        "hop_is_not_admission": False,
        "why": trace.get("why_evidence_found") or "not_found",
        "evidence_found": found,
    }


def existing_link_in_unit(text: str) -> bool:
    if OSKALIGT_RE.search(text):
        return False
    secrecy = bool(SECRECY_RE.search(text))
    exception = bool(EXCEPTION_RE.search(text) or LIST_RE.search(text))
    return secrecy and exception


def _link(yes_rows: list[dict[str, object]], others: list[str]) -> dict[str, object]:
    navigation: list[str] = []
    for row in yes_rows:
        text = str(row.get("text") or "")
        citations = [match.group(0) for match in CITATION_RE.finditer(text)]
        headings = [match.group(1).strip() for match in HEADING_RE.finditer(text)]
        if citations and not all(_contains(item, others) for item in citations):
            navigation.append("resolve_cited_material")
            continue
        if headings and not all(_contains(item, others) for item in headings):
            navigation.append("resolve_cited_material")
            continue
        if citations and all(_contains(item, others) for item in citations):
            return {"answered": True, "how": RESOLVED_CITATION, "navigation": []}
        if headings and all(_contains(item, others) for item in headings):
            return {"answered": True, "how": RESOLVED_HEADING, "navigation": []}
        if existing_link_in_unit(text):
            return {"answered": True, "how": EXISTING_LINK, "navigation": []}
        if OSKALIGT_RE.search(text) and SECRECY_RE.search(text):
            return {"answered": False, "how": OSKALIGT_NOT_CLAIM, "navigation": []}
        if ANAPHOR_RE.search(text) and not existing_link_in_unit(text):
            navigation.append("resolve_anaphor_antecedent")
    how = navigation[0] if navigation else HOP_IS_NOT_ADMISSION
    if how == "resolve_cited_material":
        how = UNRESOLVED_CITATION
    elif how == "resolve_anaphor_antecedent":
        how = UNRESOLVED_ANAPHOR
    return {"answered": False, "how": how, "navigation": list(dict.fromkeys(navigation))}


def _contains(needle: str, texts: list[str]) -> bool:
    target = needle.casefold()
    return any(target in text.casefold() for text in texts)


def _ground(row: dict[str, object]) -> dict[str, object]:
    text = str(row.get("text") or "")
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    unit_id = str(identity.get("key") or row.get("document_id") or "unit")
    span = validate_span(unit_id, text, text)
    return {
        "unit_id": span.unit_id,
        "start": span.start,
        "end": span.end,
        "text": span.text,
        "validated": span.validated,
        "char_start": identity.get("char_start"),
        "char_end": identity.get("char_end"),
    }
