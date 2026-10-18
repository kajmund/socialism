"""Shared contracts for the paired document-presentation benchmark."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import UserAccount
from app.database.workspace_models import VoiceWorkspace
from app.schemas.workspace import WorkspaceState
from app.services.document_qa.tenants import TenantCatalogs

Arm = Literal["baseline", "treatment"]
Mode = Literal["replace", "filter", "within", "extend"]
Intent = Literal["show", "count", "analyze", "ambiguous"]
FindRunner = Callable[[dict[str, Any], WorkspaceState], Awaitable[dict[str, Any]]]
ExposeTools = Callable[..., Awaitable[tuple[list[dict[str, Any]], Any]]]
CompleteTools = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class GoldCase:
    case_id: str
    message: str
    search_query: str
    mode: Mode
    current_source_ids: tuple[str, ...]
    expected_source_ids: tuple[str, ...]
    expected_gallery: bool
    intent: Intent


@dataclass(frozen=True)
class PresentationDecision:
    accepted: bool
    reason: str
    call: dict[str, Any] | None = None


@dataclass
class CallCounts:
    llm: int = 0
    jev: int = 0
    embedding: int = 0


@dataclass
class CaseResult:
    case_id: str
    arm: Arm
    intent: Intent
    mode: Mode
    latency_ms: float
    shared_initial_latency_ms: float
    continuation_latency_ms: float
    calls: CallCounts
    first_tool_called: bool
    first_arguments: dict[str, Any] | None
    search_arguments: dict[str, Any] | None
    source_ids: list[str]
    document_selection_correct: bool
    gallery_presented: bool
    presentation_decision_correct: bool
    continuation: str
    validation_reason: str | None


@dataclass(frozen=True)
class BenchmarkEnvironment:
    sessions: async_sessionmaker[AsyncSession]
    registry: TenantCatalogs
    user: UserAccount
    workspace: VoiceWorkspace
    inventory: frozenset[str]


@dataclass(frozen=True)
class ContinuationInput:
    case: GoldCase
    prompts: dict[str, str]
    specs: list[dict[str, Any]]
    state: WorkspaceState
    messages: list[dict[str, Any]]
    first: Any
    result: dict[str, Any]


@dataclass(frozen=True)
class SharedCaseExecution:
    continuation: ContinuationInput
    first_arguments: dict[str, Any]
    search_arguments: dict[str, Any]
    result: dict[str, Any]
    elapsed_ms: float
    calls: CallCounts
