"""Live Step B orchestration across text and fixed-transcript voice channels."""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from openai import OpenAIError
from pydantic import ValidationError

from app.config import EMBEDDING_MODEL_DIMENSIONS, settings
from app.database.models import SmeExpertTurn
from app.jev.system import JevClientError
from app.services import jobs as jobs_service
from app.services.document_qa.tenants import set_tenant_catalogs
from app.services.overgraph.catalogs import open_runtime, set_runtime
from app.services.persona_chat import ChatTurnError
from app.services.sme_expert_turns import (
    accept_expert_turn,
    execute_expert_turn,
    mark_expert_turn_running,
)
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_turns import group_note
from scripts.document_presentation_benchmark.cases import (
    build_gold_cases,
    state_for_case,
)
from scripts.document_presentation_benchmark.environment import CUSTOMER_ID, USER_ID
from scripts.document_presentation_benchmark.step_b_adapters import delivery_adapter
from scripts.document_presentation_benchmark.step_b_capture import (
    capture_find_calls,
    install_find_capture,
)
from scripts.document_presentation_benchmark.step_b_environment import (
    create_step_b_environment,
    persona_id,
)
from scripts.document_presentation_benchmark.step_b_types import (
    CHANNELS,
    DeliveryCapture,
    HandlerCapture,
    StepBCaseResult,
    TurnSpec,
)
from scripts.document_presentation_benchmark.types import GoldCase

ExecuteTurn = Callable[..., Awaitable[Any]]


async def run_step_b() -> dict[str, Any]:
    cases = build_gold_cases()
    with tempfile.TemporaryDirectory(prefix="document-channel-parity-") as temp:
        root = Path(temp)
        environment, engine = await create_step_b_environment(root, cases)
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
            # SQLite permits one writer. Production uses Postgres; suppress periodic
            # lease renewal here so it cannot contend with the measured turn.
            with (
                install_find_capture(),
                patch(
                    "app.services.sme_expert_turns.EXPERT_TURN_LEASE_SECONDS",
                    3600,
                ),
            ):
                rows = await run_channel_matrix(
                    cases,
                    session_factory=environment.sessions,
                    execute_turn=execute_expert_turn,
                )
        finally:
            jobs_service.set_job_session_factory(None)
            await engine.dispose()
            environment.registry.close()
            set_tenant_catalogs(None)
            set_runtime(None)
    return _payload(cases, rows)


async def run_channel_matrix(
    cases: Sequence[GoldCase],
    *,
    session_factory,
    execute_turn: ExecuteTurn,
) -> list[StepBCaseResult]:
    rows: list[StepBCaseResult] = []
    for case in cases:
        initial = state_for_case(case)
        for channel in CHANNELS:
            spec = TurnSpec(
                case=case,
                channel=channel,
                persona_id=persona_id(case, channel),
                request_id=f"step-b-{case.case_id}-{channel}",
                state=initial.model_copy(deep=True),
            )
            rows.append(
                await _run_turn(
                    spec,
                    session_factory=session_factory,
                    execute_turn=execute_turn,
                )
            )
    return rows


async def _run_turn(
    spec: TurnSpec,
    *,
    session_factory,
    execute_turn: ExecuteTurn,
) -> StepBCaseResult:
    handler = HandlerCapture()
    delivery = DeliveryCapture()
    callback = delivery_adapter(
        spec.channel,
        delivery,
        request_id=spec.request_id,
        persona_id=spec.persona_id,
    )
    started = time.perf_counter()
    error: dict[str, str] | None = None
    lifecycle_status = "not_accepted"
    try:
        fence, token = await _admit(spec, session_factory)
        lifecycle_status = "running"
        kwargs = _execute_kwargs(spec, fence=fence, token=token, callback=callback)
        with capture_find_calls(handler):
            await execute_turn(session_factory, **kwargs)
        lifecycle_status = "succeeded"
    except (
        ChatTurnError,
        HTTPException,
        JevClientError,
        OpenAIError,
        ValidationError,
        RuntimeError,
        ValueError,
        TimeoutError,
    ) as exc:
        error = {"type": type(exc).__name__, "message": str(exc)[:500]}
        lifecycle_status = await _stored_status(
            session_factory,
            spec.request_id,
            default="failed",
        )
    elapsed = (time.perf_counter() - started) * 1000
    return _result(
        spec,
        handler=handler,
        delivery=delivery,
        latency_ms=elapsed,
        lifecycle_status=lifecycle_status,
        error=error,
    )


async def _admit(spec: TurnSpec, session_factory) -> tuple[int, str]:
    async with session_factory() as session:
        turn, should_run = await accept_expert_turn(
            session,
            request_id=spec.request_id,
            customer_id=CUSTOMER_ID,
            user_id=USER_ID,
            persona_id=spec.persona_id,
            message=spec.case.message,
            image_sha256=None,
        )
        if not should_run or turn.lease_token is None:
            raise RuntimeError("step_b_turn_not_admitted")
        marked = await mark_expert_turn_running(
            session,
            spec.request_id,
            fence=turn.fence,
            token=turn.lease_token,
        )
        if not marked:
            raise RuntimeError("step_b_turn_not_running")
        await session.commit()
        return turn.fence, turn.lease_token


def _execute_kwargs(spec: TurnSpec, *, fence: int, token: str, callback) -> dict:
    kwargs = {
        "request_id": spec.request_id,
        "persona_id": spec.persona_id,
        "message": spec.case.message,
        "image_sha256": None,
        "fence": fence,
        "token": token,
        "workspace_id": "benchmark-canvas",
        "workspace_state": spec.state,
        "on_client_tools": callback,
    }
    if spec.channel != "group_voice":
        return kwargs
    panel = GroupVoiceSession(
        panel_id=f"panel-{spec.case.case_id}",
        member_ids={spec.persona_id},
        member_names={spec.persona_id: "Benchmarkjuristen"},
        floor=spec.persona_id,
        floor_reason="name",
    )
    return {**kwargs, "group_history": [], "group_note": group_note(panel)}


async def _stored_status(session_factory, request_id: str, *, default: str) -> str:
    async with session_factory() as session:
        turn = await session.get(SmeExpertTurn, request_id)
        return default if turn is None else str(turn.status)


def _result(
    spec: TurnSpec,
    *,
    handler: HandlerCapture,
    delivery: DeliveryCapture,
    latency_ms: float,
    lifecycle_status: str,
    error: dict[str, str] | None,
) -> StepBCaseResult:
    presentations = [
        event
        for event in delivery.events
        if event.get("name") in {"show_document", "show_document_set"}
    ]
    keys = {
        json.dumps(
            {"name": row.get("name"), "arguments": row.get("arguments")},
            sort_keys=True,
            ensure_ascii=False,
        )
        for row in presentations
    }
    source_ids = (
        list(handler.results[-1].get("source_ids") or [])
        if handler.results
        else []
    )
    return StepBCaseResult(
        case_id=spec.case.case_id,
        channel=spec.channel,
        intent=spec.case.intent,
        expected_mode=spec.case.mode,
        expected_source_ids=list(spec.case.expected_source_ids),
        expected_presentation=spec.case.expected_gallery,
        latency_ms=round(latency_ms, 3),
        find_calls=handler.arguments,
        find_results=handler.results,
        source_ids=source_ids,
        presentation_calls=presentations,
        duplicate_presentations=max(0, len(presentations) - len(keys)),
        envelope=delivery.envelope,
        lifecycle_status=lifecycle_status,
        error=error,
    )


def _payload(
    cases: Sequence[GoldCase],
    rows: Sequence[StepBCaseResult],
) -> dict[str, Any]:
    return {
        "experiment": "document-presentation-channel-parity-step-b-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "classification": "observational",
        "observation_reason": "Step B ran despite the failed deterministic Step A gate.",
        "environment_notes": {
            "voice_input": "fixed transcript",
            "database": "ephemeral SQLite with WAL",
            "lease_heartbeat": (
                "delayed to avoid SQLite single-writer contention; "
                "admission, fencing, and terminal persistence remain active"
            ),
            "retry_policy": "no failed stochastic cases retried",
        },
        "step_a": {"approved_for_step_b": False},
        "case_count": len(cases),
        "channels": list(CHANNELS),
        "actual_execute_expert_turn_calls": len(rows),
        "summary": _summary(rows),
        "cases": [asdict(row) for row in rows],
    }


def _summary(rows: Sequence[StepBCaseResult]) -> dict[str, Any]:
    return {
        channel: _channel_summary([row for row in rows if row.channel == channel])
        for channel in CHANNELS
    }


def _channel_summary(rows: list[StepBCaseResult]) -> dict[str, Any]:
    latencies = sorted(row.latency_ms for row in rows)
    return {
        "turns": len(rows),
        "latency_ms": {
            "median": round(statistics.median(latencies), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
        },
        "wrong_document_selections": sum(
            row.source_ids != row.expected_source_ids for row in rows
        ),
        "wrong_mode_transitions": sum(
            not row.find_calls
            or any(call.get("mode", "replace") != row.expected_mode for call in row.find_calls)
            for row in rows
        ),
        "erroneous_auto_displays": sum(
            not row.expected_presentation and bool(row.presentation_calls) for row in rows
        ),
        "missed_explicit_shows": sum(
            row.expected_presentation and not row.presentation_calls for row in rows
        ),
        "duplicate_presentations": sum(row.duplicate_presentations for row in rows),
        "external_or_model_errors": sum(row.error is not None for row in rows),
    }


def _percentile(values: Sequence[float], fraction: float) -> float:
    rank = (len(values) - 1) * fraction
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return values[lower] * (1 - weight) + values[upper] * weight

