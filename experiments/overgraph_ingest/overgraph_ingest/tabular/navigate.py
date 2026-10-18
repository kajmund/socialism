"""Valid hops for the current unit. Jev does not invent targets."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.navigation.hop import (
    Hop,
    child_clause_hops,
    referenced_clause_hops,
    section_hops,
)
from overgraph_ingest.retrieval.index import StoredUnit

PREVIOUS = "PREVIOUS"
NEXT = "NEXT"
PARENT = "PARENT"
CHILDREN = "CHILDREN"
SAME_SECTION = "SAME_SECTION"
RESOLVE_REFERENCE = "RESOLVE_REFERENCE"
OPERATIONS = (PREVIOUS, NEXT, PARENT, CHILDREN, SAME_SECTION, RESOLVE_REFERENCE)
ABSENT = "ABSENT"
AMBIGUOUS = "AMBIGUOUS"
MAX_NAV_STEPS = 3
MAX_UNITS = 10


@dataclass(frozen=True)
class NavOption:
    operation: str
    target_key: str
    reference: str | None
    relation: str
    text: str
    clause_number: str

    @property
    def choice_id(self) -> str:
        return f"{self.operation}:{self.target_key}"


@dataclass(frozen=True)
class NavOffer:
    options: tuple[NavOption, ...]
    reports: tuple[dict[str, object], ...]


def valid_operations(
    start: StoredUnit,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
    visited: set[str],
) -> NavOffer:
    local = [unit for unit in units if unit.relative_path == start.relative_path]
    options: list[NavOption] = []
    reports: list[dict[str, object]] = []
    seen: set[str] = set()
    for hop in section_hops(start, local, structures):
        operation = _section_operation(hop.relation)
        if operation is None:
            continue
        _add_option(options, seen, visited, hop, operation, reference=None)
    for hop in parent_hops(start, local, structures):
        _add_option(options, seen, visited, hop, PARENT, reference=None)
    for hop in child_clause_hops(start, local, structures):
        _add_option(options, seen, visited, hop, CHILDREN, reference=None)
    reference, hops = referenced_clause_hops(start, local, structures)
    unused = [hop for hop in hops if hop.key not in visited]
    if reference and len(unused) == 1:
        _add_option(
            options, seen, visited, unused[0], RESOLVE_REFERENCE, reference=reference
        )
    elif reference and not unused:
        reports.append(
            {
                "operation": RESOLVE_REFERENCE,
                "reference": reference,
                "status": ABSENT if not hops else "VISITED",
            }
        )
    elif reference:
        reports.append(
            {
                "operation": RESOLVE_REFERENCE,
                "reference": reference,
                "status": AMBIGUOUS,
                "candidates": [hop.key for hop in unused],
            }
        )
    return NavOffer(tuple(options), tuple(reports))


def parent_hops(
    start: StoredUnit,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> list[Hop]:
    parent_id = str(structures.get(start.structure_id, {}).get("parent_id") or "")
    if not parent_id:
        return []
    hops: list[Hop] = []
    for unit in units:
        if unit.document_id != start.document_id or unit.key == start.key:
            continue
        if unit.structure_id != parent_id:
            continue
        props = structures.get(unit.structure_id, {})
        hops.append(
            Hop(
                key=unit.key,
                relative_path=unit.relative_path,
                relation=PARENT,
                text=unit.text,
                structure_title=str(props.get("title") or ""),
                clause_number=str(props.get("clause_number") or ""),
            )
        )
    return hops


def option_by_choice(offer: NavOffer, choice_id: str) -> NavOption | None:
    for option in offer.options:
        if option.choice_id == choice_id:
            return option
    return None


def _section_operation(relation: str) -> str | None:
    if relation == PREVIOUS:
        return PREVIOUS
    if relation == NEXT:
        return NEXT
    if relation == SAME_SECTION:
        return SAME_SECTION
    return None


def _add_option(
    options: list[NavOption],
    seen: set[str],
    visited: set[str],
    hop: Hop,
    operation: str,
    *,
    reference: str | None,
) -> None:
    choice_id = f"{operation}:{hop.key}"
    if hop.key in visited or choice_id in seen:
        return
    seen.add(choice_id)
    options.append(
        NavOption(
            operation=operation,
            target_key=hop.key,
            reference=reference,
            relation=hop.relation,
            text=hop.text,
            clause_number=hop.clause_number,
        )
    )
