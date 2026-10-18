"""Contracts for captured channel deliveries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Channel = Literal["text", "voice", "group"]


@dataclass(frozen=True)
class Capture:
    channel: Channel
    case_id: str
    expected_gallery: bool
    expected_source_ids: tuple[str, ...]
    mode: str
    state_before: dict
    raw_events: tuple[dict, ...]
    input_call_after: dict | None


@dataclass(frozen=True)
class SemanticDelivery:
    sequence: tuple[str, ...]
    source_ids: tuple[str, ...]
    duplicate_count: int
    turn_id_present: bool
