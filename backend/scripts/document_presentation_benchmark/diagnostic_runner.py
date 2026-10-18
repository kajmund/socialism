"""Nine-turn diagnostic trace for document selection and presentation."""

from __future__ import annotations

import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from openai import OpenAIError
from pydantic import ValidationError

from app.config import EMBEDDING_MODEL_DIMENSIONS, settings
from app.jev.system import JevClientError
from app.schemas.workspace import WorkspaceDocumentSet, WorkspaceState
from app.services import jobs as jobs_service
from app.services.document_find.taxonomy import EMPLOYMENT, LEASE
from app.services.document_qa.tenants import set_tenant_catalogs
from app.services.overgraph.catalogs import open_runtime, set_runtime
from app.services.persona_chat import ChatTurnError
from app.services.sme_expert_turns import execute_expert_turn
from scripts.document_presentation_benchmark.cases import fixture_inventory
from scripts.document_presentation_benchmark.diagnostic_capture import (
    DiagnosticCapture,
    capture_diagnostics,
    install_diagnostic_capture,
)
from scripts.document_presentation_benchmark.step_b_adapters import delivery_adapter
from scripts.document_presentation_benchmark.step_b_capture import (
    capture_find_calls,
    install_find_capture,
)
from scripts.document_presentation_benchmark.step_b_environment import (
    create_step_b_environment,
    persona_id,
)
from scripts.document_presentation_benchmark.step_b_runner import (
    _admit,
    _execute_kwargs,
    _result,
    _stored_status,
)
from scripts.document_presentation_benchmark.step_b_types import (
    CHANNELS,
    Channel,
    DeliveryCapture,
    HandlerCapture,
    TurnSpec,
)
from scripts.document_presentation_benchmark.types import GoldCase

ERRORS = (
    ChatTurnError,
    HTTPException,
    JevClientError,
    OpenAIError,
    ValidationError,
    RuntimeError,
    ValueError,
    TimeoutError,
)


async def run_diagnostic(
    *,
    channels: tuple[Channel, ...] = CHANNELS,
    scenario_sequences: tuple[int, ...] = (1, 2, 3),
) -> dict[str, Any]:
    seed = _case(1, WorkspaceState())
    with tempfile.TemporaryDirectory(prefix="document-channel-diagnostic-") as temp:
        root = Path(temp)
        environment, engine = await create_step_b_environment(root, [seed])
        set_runtime(
            open_runtime(
                root / "runtime-overgraph",
                knowledge_dimension=settings.embedding_dimension,
                memory_dimension=EMBEDDING_MODEL_DIMENSIONS[
                    settings.mem0_embedding_model
                ],
            )
        )
        jobs_service.set_job_session_factory(environment.sessions)
        try:
            with (
                install_find_capture(),
                install_diagnostic_capture(),
                patch(
                    "app.services.sme_expert_turns.EXPERT_TURN_LEASE_SECONDS",
                    3600,
                ),
            ):
                rows = await _run_channels(
                    environment.sessions,
                    channels=channels,
                    scenario_sequences=scenario_sequences,
                )
        finally:
            jobs_service.set_job_session_factory(None)
            await engine.dispose()
            environment.registry.close()
            set_tenant_catalogs(None)
            set_runtime(None)
    return {
        "experiment": "document-channel-nine-turn-diagnostic-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "classification": "diagnostic-only",
        "channels": list(channels),
        "scenario_sequences": list(scenario_sequences),
        "retry_policy": "one attempt per channel and scenario",
        "rows": rows,
        "summary": _summary(rows),
    }


async def _run_channels(
    session_factory,
    *,
    channels: tuple[Channel, ...] = CHANNELS,
    scenario_sequences: tuple[int, ...] = (1, 2, 3),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for channel in channels:
        state = WorkspaceState()
        history: list[tuple[str, str, str | None, str | None]] = []
        for sequence in scenario_sequences:
            case = _case(sequence, state)
            spec = TurnSpec(
                case=case,
                channel=channel,
                persona_id=persona_id(_case(1, WorkspaceState()), channel),
                request_id=f"diagnostic-{channel}-{sequence}",
                state=state.model_copy(deep=True),
            )
            row, reply, events = await _run_one(
                spec,
                session_factory=session_factory,
                group_history=history,
            )
            payload = asdict(row)
            payload["trace"] = events
            payload["breakpoint"] = _breakpoint(payload)
            rows.append(payload)
            if row.source_ids:
                state = _state(row.source_ids)
            if channel == "group_voice" and reply:
                history.extend(
                    (
                        ("user", case.message, None, None),
                        ("assistant", reply, None, None),
                    )
                )
    return rows


async def _run_one(
    spec: TurnSpec,
    *,
    session_factory,
    group_history: list[tuple[str, str, str | None, str | None]],
) -> tuple[Any, str, list[dict[str, Any]]]:
    handler = HandlerCapture()
    delivery = DeliveryCapture()
    diagnostic = DiagnosticCapture()
    callback = delivery_adapter(
        spec.channel,
        delivery,
        request_id=spec.request_id,
        persona_id=spec.persona_id,
    )
    started = time.perf_counter()
    error: dict[str, str] | None = None
    lifecycle_status = "not_accepted"
    reply = ""
    try:
        fence, token = await _admit(spec, session_factory)
        lifecycle_status = "running"
        kwargs = _execute_kwargs(spec, fence=fence, token=token, callback=callback)
        if spec.channel == "group_voice":
            kwargs["group_history"] = list(group_history)
        with capture_find_calls(handler), capture_diagnostics(diagnostic):
            completed = await execute_expert_turn(session_factory, **kwargs)
        reply = completed.reply or ""
        lifecycle_status = "succeeded"
    except ERRORS as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        lifecycle_status = await _stored_status(
            session_factory,
            spec.request_id,
            default="failed",
        )
    elapsed = (time.perf_counter() - started) * 1000
    row = _result(
        spec,
        handler=handler,
        delivery=delivery,
        latency_ms=elapsed,
        lifecycle_status=lifecycle_status,
        error=error,
    )
    return row, reply, diagnostic.events


def _case(sequence: int, state: WorkspaceState) -> GoldCase:
    current = tuple(_active_ids(state))
    inventory = fixture_inventory()
    if sequence == 1:
        return GoldCase(
            case_id="diagnostic",
            message="Visa alla hyresavtal.",
            search_query="hyresavtal",
            mode="replace",
            current_source_ids=current,
            expected_source_ids=inventory[LEASE],
            expected_gallery=True,
            intent="show",
        )
    if sequence == 2:
        return GoldCase(
            case_id="diagnostic-filter",
            message="Visa bara dem med automatisk förlängning.",
            search_query="automatisk förlängning",
            mode="filter",
            current_source_ids=current,
            expected_source_ids=current,
            expected_gallery=True,
            intent="show",
        )
    return GoldCase(
        case_id="diagnostic-extend",
        message="Lägg till anställningsavtalen.",
        search_query="anställningsavtal",
        mode="extend",
        current_source_ids=current,
        expected_source_ids=tuple(dict.fromkeys((*current, *inventory[EMPLOYMENT]))),
        expected_gallery=True,
        intent="show",
    )


def _state(source_ids: list[str]) -> WorkspaceState:
    return WorkspaceState(
        view="document_set",
        document_sets=[
            WorkspaceDocumentSet(
                id="diagnostic-active",
                title="Diagnostiskt dokumenturval",
                source_ids=source_ids,
            )
        ],
        active_document_set_id="diagnostic-active",
    )


def _active_ids(state: WorkspaceState) -> list[str]:
    active = next(
        (
            item
            for item in state.document_sets
            if item.id == state.active_document_set_id
        ),
        None,
    )
    return [] if active is None else list(active.source_ids)


def _breakpoint(row: dict[str, Any]) -> str:
    trace = row["trace"]
    initial_route = _event(trace, "initial_route")
    initial_model = _event(trace, "initial_model")
    post_route = _event(trace, "post_result_route")
    continuation = _event(trace, "continuation_model")
    checks = (
        (
            initial_route is None
            or "find_documents" not in initial_route.get("exposed", []),
            "initial_tool_routing",
        ),
        (
            initial_model is None
            or "find_documents" not in _call_names(initial_model),
            "initial_model_decision",
        ),
        (not row["find_calls"], "find_dispatch"),
        (not row["find_results"], "document_search"),
        (post_route is None, "post_result_routing"),
        (
            post_route is not None
            and "show_document_set" not in post_route.get("exposed", []),
            "continuation_tool_exposure",
        ),
        (
            continuation is None or bool(continuation.get("error")),
            "continuation_model_error",
        ),
        (
            continuation is not None
            and "show_document_set" not in _call_names(continuation),
            "continuation_model_decision",
        ),
        (not row["presentation_calls"], "client_delivery"),
    )
    return next((stage for failed, stage in checks if failed), "completed")


def _event(events: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
    return next((event for event in events if event.get("stage") == stage), None)


def _call_names(event: dict[str, Any]) -> set[str]:
    return {str(call.get("name") or "") for call in event.get("tool_calls", [])}


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        channel: {
            "breakpoints": _counts(
                row["breakpoint"] for row in rows if row["channel"] == channel
            ),
            "errors": _counts(
                row["error"]["type"]
                for row in rows
                if row["channel"] == channel and row["error"] is not None
            ),
        }
        for channel in {row["channel"] for row in rows}
    }


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
