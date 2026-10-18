"""Result contracts for the observational live channel-parity run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.schemas.workspace import WorkspaceState
from scripts.document_presentation_benchmark.types import GoldCase

Channel = Literal["text", "voice", "group_voice"]
CHANNELS: tuple[Channel, ...] = ("text", "voice", "group_voice")


@dataclass
class HandlerCapture:
    arguments: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DeliveryCapture:
    events: list[dict[str, Any]] = field(default_factory=list)
    envelope: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnSpec:
    case: GoldCase
    channel: Channel
    persona_id: str
    request_id: str
    state: WorkspaceState


@dataclass
class StepBCaseResult:
    case_id: str
    channel: Channel
    intent: str
    expected_mode: str
    expected_source_ids: list[str]
    expected_presentation: bool
    latency_ms: float
    find_calls: list[dict[str, Any]]
    find_results: list[dict[str, Any]]
    source_ids: list[str]
    presentation_calls: list[dict[str, Any]]
    duplicate_presentations: int
    envelope: dict[str, Any]
    lifecycle_status: str
    error: dict[str, str] | None

