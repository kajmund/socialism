"""Safety gate: reference identity and unresolved polarity. Not a Jev prompt."""

from __future__ import annotations

import re

from overgraph_ingest.coverage.proof_link import CLAUSE_HEAD_RE
from overgraph_ingest.navigation.hop import PUNKT_RE

UNDECIDED = "UNDECIDED"
POLARITY_RESOLVED = "resolved"
POLARITY_UNRESOLVED = "unresolved"
NEGATION_RE = re.compile(r"\binte\b", re.I)
INNER_EXCEPTION_RE = re.compile(r"\b(?:utom|dock|endast)\b", re.I)
DOCK_INTE_RE = re.compile(r"\bdock\s+inte\b", re.I)
STACKED_POLARITY_CLASS = (
    "Begränsningen gäller inte, utom vid sekretessbrott.",
    "Begränsningen gäller inte, dock vid sekretessbrott.",
    "Begränsningen gäller inte, endast vid sekretessbrott.",
    "Ansvarsbegränsningen gäller inte utom vid brott mot sekretess.",
)


def reference_integrity(source: str, target: str) -> dict[str, object]:
    """Punkt N may only resolve to clause N. Jev does not pick the target."""
    match = PUNKT_RE.search(source)
    if match is None:
        return {
            "has_reference": False,
            "reference": None,
            "target_clause": _clause_number(target),
            "referent_matches": False,
            "status": "no_reference",
        }
    reference = match.group(1)
    target_clause = _clause_number(target)
    matches = _clause_matches(reference, target_clause)
    return {
        "has_reference": True,
        "reference": reference,
        "target_clause": target_clause,
        "referent_matches": matches,
        "status": "resolved" if matches else "unresolved",
    }


def polarity_status(text: str) -> str:
    """Stacked polarity operators are unresolved. The gate refuses, it does not parse."""
    stripped = DOCK_INTE_RE.sub(" inte ", text)
    if NEGATION_RE.search(stripped) and INNER_EXCEPTION_RE.search(stripped):
        return POLARITY_UNRESOLVED
    return POLARITY_RESOLVED


def admit_supported(
    predicted: str,
    *,
    reference: dict[str, object] | None = None,
    polarity: str = POLARITY_RESOLVED,
) -> dict[str, object]:
    """SUPPORTED may pass only with a resolved referent and resolved polarity."""
    if predicted != "SUPPORTED":
        return {"admitted": predicted, "blocked": False, "reason": None}
    if reference is not None:
        if not reference.get("has_reference"):
            return {"admitted": UNDECIDED, "blocked": True, "reason": "no_reference"}
        if not reference.get("referent_matches"):
            return {"admitted": UNDECIDED, "blocked": True, "reason": "unresolved_reference"}
    if polarity == POLARITY_UNRESOLVED:
        return {"admitted": UNDECIDED, "blocked": True, "reason": "unresolved_polarity"}
    return {"admitted": "SUPPORTED", "blocked": False, "reason": None}


def admit_complete(
    *,
    yes_texts: list[str],
    hop_pairs: list[tuple[str, str]],
) -> dict[str, object]:
    """Refuse a complete mark when polarity is stacked or a hop misses its clause."""
    for text in yes_texts:
        if polarity_status(text) == POLARITY_UNRESOLVED:
            return {
                "admitted": False,
                "blocked": True,
                "reason": "unresolved_polarity",
            }
    for source, target in hop_pairs:
        integrity = reference_integrity(source, target)
        if integrity["has_reference"] and not integrity["referent_matches"]:
            return {
                "admitted": False,
                "blocked": True,
                "reason": "unresolved_reference",
            }
    return {"admitted": True, "blocked": False, "reason": None}


def _clause_number(text: str) -> str | None:
    match = CLAUSE_HEAD_RE.search(text.strip())
    return None if match is None else match.group(1)


def _clause_matches(reference: str, clause: str | None) -> bool:
    if clause is None:
        return False
    return clause == reference or clause.startswith(f"{reference}.")
