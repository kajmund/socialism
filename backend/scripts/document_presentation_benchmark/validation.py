"""Experiment-only schema adaptation and deterministic presentation gate."""

from __future__ import annotations

import json
from typing import Any

from scripts.document_presentation_benchmark.types import PresentationDecision

EXPERIMENT_INSTRUCTION = (
    "Experimentregel: find_documents har ett valfritt presentation-fält. Sätt "
    'presentation till "gallery" endast när användaren uttryckligen ber att '
    "dokumenten ska visas eller öppnas som en mängd. Utelämna fältet för "
    "räkning, analysförberedelse och tvetydiga frågor."
)


def experimental_find_spec(production_spec: dict[str, Any]) -> dict[str, Any]:
    """Clone the production schema and add the experiment-only field."""
    clone = json.loads(json.dumps(production_spec))
    function = clone["function"]
    parameters = function["parameters"]
    parameters["properties"]["presentation"] = {
        "type": "string",
        "enum": ["gallery"],
        "description": (
            "Only for an explicit request to display the resulting documents. "
            "Omit for count, analysis, or ambiguous intent."
        ),
    }
    function["description"] = (
        f"{function['description']}\n\n{EXPERIMENT_INSTRUCTION}"
    )
    return clone


def production_find_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove the experiment-only field before production dispatch."""
    return {key: value for key, value in arguments.items() if key != "presentation"}


def validate_gallery_continuation(
    arguments: dict[str, Any],
    result: dict[str, Any],
    *,
    allowed_source_ids: frozenset[str],
) -> PresentationDecision:
    """Fail closed unless every deterministic gallery condition is satisfied."""
    reason = None
    full_ids = result.get("source_ids")
    shown_ids = result.get("presentation_source_ids")
    if arguments.get("presentation") != "gallery":
        reason = "presentation_not_gallery"
    elif result.get("status") not in {"success", "completed"}:
        reason = "find_not_completed"
    elif result.get("completeness") != "complete":
        reason = "find_not_complete"
    elif not _valid_unique_strings(full_ids):
        reason = "invalid_full_source_ids"
    elif not _valid_unique_strings(shown_ids):
        reason = "invalid_presentation_source_ids"
    elif not set(full_ids) <= allowed_source_ids:
        reason = "source_outside_inventory"
    elif not set(shown_ids) <= set(full_ids):
        reason = "presentation_not_subset"
    if reason is not None:
        return PresentationDecision(False, reason)
    call = {
        "name": "show_document_set",
        "arguments": {
            "title": str(result.get("title") or "Dokument")[:255],
            "source_ids": list(shown_ids),
        },
    }
    return PresentationDecision(True, "accepted", call)


def _valid_unique_strings(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
        and len(value) == len(set(value))
    )
