"""Linked legal relation, not keyword co-occurrence. Not a Coverage v3 rule."""

from __future__ import annotations

import re

from overgraph_ingest.coverage.proof_relation import COMPONENT_PATTERNS, RELATION
from overgraph_ingest.navigation.hop import PUNKT_RE

PROOF_LINK = "link"
LINKED_RELATION = "linked_relation"
NEEDS_NAVIGATION = "needs_navigation"
NOT_GROUNDED = "not_grounded"
LINK_RE = re.compile(
    r"(?:gäller\s+inte|utom\s+vid|dock\s+inte).{0,200}sekretess",
    re.I,
)
CLAUSE_HEAD_RE = re.compile(r"^(\d+(?:\.\d+)*)\.", re.M)


def evaluate_passage(text: str) -> dict[str, object]:
    link = LINK_RE.search(text)
    reference = PUNKT_RE.search(text)
    components = {
        name: None if match is None else match.group(0)
        for name, pattern in COMPONENT_PATTERNS.items()
        for match in [pattern.search(text)]
    }
    if link is not None:
        status = LINKED_RELATION
    elif reference is not None and components["exception"] and not components["secrecy_breach"]:
        status = NEEDS_NAVIGATION
    else:
        status = NOT_GROUNDED
    return {
        "text": text,
        "status": status,
        "linked_span": None if link is None else link.group(0),
        "reference": None if reference is None else reference.group(1),
        "components": components,
        "grounding_passage": text if status == LINKED_RELATION else None,
    }


def evaluate_passages(texts: list[str]) -> dict[str, object]:
    """Judge each passage on its own. Do not join words across units."""
    passages = [evaluate_passage(text) for text in texts]
    linked = next((row for row in passages if row["status"] == LINKED_RELATION), None)
    pending = next((row for row in passages if row["status"] == NEEDS_NAVIGATION), None)
    bag = "\n".join(texts)
    bag_components = {
        name: bool(pattern.search(bag)) for name, pattern in COMPONENT_PATTERNS.items()
    }
    cooccurrence_only = linked is None and all(bag_components[name] for name in RELATION)
    if linked is not None:
        status = LINKED_RELATION
    elif pending is not None:
        status = NEEDS_NAVIGATION
    else:
        status = NOT_GROUNDED
    return {
        "status": status,
        "passages": passages,
        "grounding_passage": None if linked is None else linked["grounding_passage"],
        "linked_span": None if linked is None else linked["linked_span"],
        "cooccurrence_only": cooccurrence_only,
        "bag_components": bag_components,
    }


def resolve_reference(source: str, target: str) -> dict[str, object]:
    """A hop target may only ground the referenced clause, not a later heading."""
    source_row = evaluate_passage(source)
    if source_row["status"] == LINKED_RELATION:
        return {
            **evaluate_passages([source, target]),
            "resolved": True,
            "referent_matches": False,
        }
    ref = source_row["reference"]
    target_clause = _clause_number(target)
    referent_matches = bool(ref) and _clause_matches(ref, target_clause)
    target_row = evaluate_passage(target)
    if source_row["status"] != NEEDS_NAVIGATION or not referent_matches:
        combined = evaluate_passages([source, target])
        return {
            "status": NOT_GROUNDED,
            "passages": [source_row, target_row],
            "grounding_passage": None,
            "linked_span": None,
            "cooccurrence_only": combined["cooccurrence_only"],
            "bag_components": combined["bag_components"],
            "resolved": False,
            "referent_matches": referent_matches,
        }
    secrecy = bool(COMPONENT_PATTERNS["secrecy_breach"].search(target))
    status = LINKED_RELATION if secrecy else NOT_GROUNDED
    return {
        "status": status,
        "passages": [source_row, target_row],
        "grounding_passage": target if status == LINKED_RELATION else None,
        "linked_span": source_row.get("linked_span"),
        "cooccurrence_only": False,
        "bag_components": {
            name: bool(pattern.search(f"{source}\n{target}"))
            for name, pattern in COMPONENT_PATTERNS.items()
        },
        "resolved": True,
        "referent_matches": True,
    }


def _clause_number(text: str) -> str | None:
    match = CLAUSE_HEAD_RE.search(text.strip())
    return None if match is None else match.group(1)


def _clause_matches(reference: str, clause: str | None) -> bool:
    if clause is None:
        return False
    return clause == reference or clause.startswith(f"{reference}.")
