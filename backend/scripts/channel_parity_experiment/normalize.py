"""Normalize captured envelopes only after production adapters emit them."""

from __future__ import annotations

from scripts.channel_parity_experiment.types import Capture, SemanticDelivery


def normalize(capture: Capture) -> SemanticDelivery:
    calls = [
        event
        for event in capture.raw_events
        if event.get("type") in {"workspace_tool", "workspace.tool"}
    ]
    sequence = tuple(str(event.get("name") or "") for event in calls)
    source_ids = tuple(
        source_id
        for event in calls
        for source_id in event.get("arguments", {}).get("source_ids", [])
    )
    identities = [
        (
            event.get("name"),
            tuple(event.get("arguments", {}).get("source_ids", [])),
        )
        for event in calls
    ]
    return SemanticDelivery(
        sequence=sequence,
        source_ids=source_ids,
        duplicate_count=len(identities) - len(set(identities)),
        turn_id_present=all(_turn_id(event) for event in calls),
    )


def _turn_id(event: dict) -> bool:
    return bool(event.get("turn_id") or event.get("request_id"))
