"""Frozen 50-case gold set and conversational workspace state.

``expected_gallery`` records what each case instructs the model to do; it is not
a system-level suppression. The deterministic presentation gate was removed, so
the model and the tool descriptions decide whether a gallery is shown.
"""

from __future__ import annotations

from app.schemas.workspace import WorkspaceDocumentSet, WorkspaceState
from app.services.document_find.taxonomy import (
    CONSULTING,
    EMPLOYMENT,
    LEASE,
    NDA,
    SUPPLY,
    TYPE_LABELS_SV,
)
from scripts.document_presentation_benchmark.types import GoldCase, Intent, Mode

DOCUMENT_TYPES = (LEASE, EMPLOYMENT, CONSULTING, NDA, SUPPLY)


def build_gold_cases() -> list[GoldCase]:
    """Build exactly 50 paired cases across all modes and intent classes."""
    inventory = fixture_inventory()
    modes: tuple[Mode, ...] = ("replace", "filter", "within", "extend", "replace")
    no_show_intents: tuple[Intent, ...] = ("count", "analyze", "ambiguous")
    cases: list[GoldCase] = []
    for index in range(25):
        document_type = DOCUMENT_TYPES[index % len(DOCUMENT_TYPES)]
        label = TYPE_LABELS_SV[document_type]
        variation = index // len(DOCUMENT_TYPES)
        mode = modes[(index + variation) % len(modes)]
        current = _current_set(index, document_type, inventory, mode)
        expected = _expected_selection(document_type, mode, current, inventory)
        search_query = _search_query(label, variation)
        pair_id = f"{index + 1:02d}"
        cases.append(
            GoldCase(
                case_id=f"{pair_id}-show",
                message=_case_message(label, mode, variation, show=True),
                search_query=search_query,
                mode=mode,
                current_source_ids=current,
                expected_source_ids=expected,
                expected_gallery=True,
                intent="show",
            )
        )
        intent = no_show_intents[index % len(no_show_intents)]
        cases.append(
            GoldCase(
                case_id=f"{pair_id}-{intent}",
                message=_case_message(
                    label,
                    mode,
                    variation,
                    show=False,
                    intent=intent,
                ),
                search_query=search_query,
                mode=mode,
                current_source_ids=current,
                expected_source_ids=expected,
                expected_gallery=False,
                intent=intent,
            )
        )
    if len(cases) != 50:
        raise AssertionError("gold case count changed")
    return cases


def state_for_case(case: GoldCase) -> WorkspaceState:
    if not case.current_source_ids:
        return WorkspaceState()
    return WorkspaceState(
        view="document_set",
        document_sets=[
            WorkspaceDocumentSet(
                id="current-set",
                title="Aktuell dokumentmängd",
                source_ids=list(case.current_source_ids),
            )
        ],
        active_document_set_id="current-set",
    )


def fixture_inventory() -> dict[str, tuple[str, ...]]:
    return {
        document_type: tuple(source_id(document_type, ordinal) for ordinal in range(4))
        for document_type in DOCUMENT_TYPES
    }


def source_id(document_type: str, ordinal: int) -> str:
    return f"src-{document_type}-{ordinal}"


def _current_set(
    index: int,
    document_type: str,
    inventory: dict[str, tuple[str, ...]],
    mode: Mode,
) -> tuple[str, ...]:
    variation = index // len(DOCUMENT_TYPES)
    if mode == "replace" and variation == 0:
        return ()
    other_type = DOCUMENT_TYPES[(index + 1) % len(DOCUMENT_TYPES)]
    target = inventory[document_type]
    other = inventory[other_type]
    offset = variation % 3
    if mode in {"filter", "within"}:
        return (
            target[offset],
            target[offset + 1],
            other[offset],
            other[offset + 1],
        )
    return (other[offset], other[offset + 1])


def _expected_selection(
    document_type: str,
    mode: Mode,
    current: tuple[str, ...],
    inventory: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    found = inventory[document_type]
    if mode in {"filter", "within"} and current:
        return tuple(source for source in found if source in current)
    if mode == "extend" and current:
        return tuple(dict.fromkeys((*current, *found)))
    return found


def _search_query(label: str, variation: int) -> str:
    templates = (
        "{label}",
        "Visa alla {label}",
        "Alla {label}",
        "Visa dokument {label}",
        "Visa alla dokument {label}",
    )
    return templates[variation].format(label=label)


def _case_message(
    label: str,
    mode: Mode,
    variation: int,
    *,
    show: bool,
    intent: Intent = "show",
) -> str:
    opening = _mode_instruction(label, mode, variation)
    if show:
        endings = (
            "Visa dem som ett galleri.",
            "Öppna resultatet som dokumentgalleri.",
            "Jag vill se dokumentmängden.",
            "Presentera träffarna i ett galleri.",
            "Visa de hittade dokumenten tillsammans.",
        )
        return f"{opening} {endings[variation]}"
    return f"{opening} {_no_show_instruction(intent)}"


def _mode_instruction(label: str, mode: Mode, variation: int) -> str:
    noun = label.lower()
    if mode == "filter":
        return f"Filtrera den aktuella dokumentmängden till {noun}."
    if mode == "within":
        return f"Sök inom den aktuella dokumentmängden efter {noun}."
    if mode == "extend":
        return f"Lägg till {noun} i den aktuella dokumentmängden."
    openings = ("Hitta", "Ta fram", "Sök fram", "Identifiera", "Hämta fram")
    return f"{openings[variation]} {noun}."


def _no_show_instruction(intent: Intent) -> str:
    if intent == "count":
        return "Svara bara hur många det är och visa inget galleri."
    if intent == "analyze":
        return "Detta är underlag för en senare analys; visa dem inte nu."
    return "Vad har vi för sådana dokument?"
