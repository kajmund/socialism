"""Rule B: complete legal relation in text. Not a Coverage v3 controller."""

from __future__ import annotations

import re

from overgraph_ingest.navigation.hop import PUNKT_RE

RELATION = ("liability_cap", "exception", "secrecy_breach")
COMPLETE_IN_UNIT = "complete_in_unit"
NEEDS_COMPLEMENTARY = "needs_complementary_units"
UNRESOLVED_REFERENCE = "unresolved_reference"
CURRENT_HOP = "current_requires_hop"
PROOF_CURRENT = "current"
PROOF_RELATION = "relation"
COMPONENT_PATTERNS = {
    "liability_cap": re.compile(
        r"ansvar(?:et)?(?:\s+för\s+skada)?\s+är\s+begränsat|ansvarsbegräns|"
        r"begränsningarna|sammanlagda\s+ansvar",
        re.I,
    ),
    "exception": re.compile(r"gäller\s+inte|utom\s+vid|dock\s+inte", re.I),
    "secrecy_breach": re.compile(r"sekretess", re.I),
}


def evidence_in_text(text: str) -> dict[str, object]:
    spans = {}
    for name, pattern in COMPONENT_PATTERNS.items():
        match = pattern.search(text)
        spans[name] = None if match is None else match.group(0)
    reference = PUNKT_RE.search(text)
    missing = [name for name in RELATION if not spans[name]]
    if reference is not None and not spans["secrecy_breach"]:
        status = UNRESOLVED_REFERENCE
    elif missing:
        status = NEEDS_COMPLEMENTARY
    else:
        status = COMPLETE_IN_UNIT
    return {
        "text": text,
        "components": spans,
        "missing_components": missing,
        "reference": None if reference is None else reference.group(1),
        "relation_complete_in_unit": status == COMPLETE_IN_UNIT,
        "status": status,
    }


def proposed_status(
    evidence: dict[str, object], *, missing_coverage_parts: tuple[str, ...]
) -> str:
    if evidence["status"] == UNRESOLVED_REFERENCE:
        return UNRESOLVED_REFERENCE
    if missing_coverage_parts:
        return NEEDS_COMPLEMENTARY
    return str(evidence["status"])


def current_status() -> str:
    return CURRENT_HOP


def relation_status(
    *,
    texts: list[str],
    required_parts: tuple[str, ...],
) -> str:
    for text in texts:
        evidence = evidence_in_text(text)
        missing_parts = tuple(part for part in required_parts if part not in text)
        status = proposed_status(evidence, missing_coverage_parts=missing_parts)
        if status == COMPLETE_IN_UNIT:
            return COMPLETE_IN_UNIT
    joined = "\n".join(texts)
    missing_parts = tuple(part for part in required_parts if part not in joined)
    return proposed_status(
        evidence_in_text(joined),
        missing_coverage_parts=missing_parts,
    )
