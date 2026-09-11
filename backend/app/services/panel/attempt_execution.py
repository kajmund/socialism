"""ExecutionAttempt.ready → frozen EvidenceSet → generic_panel → completed."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExecutionAttempt, ExecutionAttemptResult, PanelSession
from app.services.execution.errors import ExecutionError, ExecutionStatusError
from app.services.execution.evidence_render import RenderedEvidence, render_frozen_evidence
from app.services.execution.service import (
    claim_attempt_running,
    complete_attempt,
    fail_attempt,
    get_attempt,
    get_attempt_result,
    get_run,
    list_evidence_items,
    persist_attempt_result,
    require_frozen_evidence_for_attempt,
)
from app.services.panel.engine import run_generic_panel
from app.services.panel.result import PanelResult
from app.services.panel.schemas import PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.prompt_catalog import render_prompt

GENERIC_PANEL_ATTEMPT_TYPE = "generic_panel"
GENERIC_PANEL_RESULT_TYPE = "generic_panel"
GENERIC_PANEL_RESULT_SCHEMA = "2"

PanelRunner = Callable[..., Awaitable[PanelSession]]


class PanelAttemptError(ExecutionError):
    """Orchestration could not finish generic_panel; Attempt is marked failed."""


@dataclass(frozen=True)
class AttemptPanelResult:
    attempt_id: str
    evidence_set_id: str | None
    status: str
    result_id: str | None
    panel_session_id: str | None
    panel_result: PanelResult | None


def _compatible_attempt_type(attempt_type: str) -> bool:
    return attempt_type.strip() == GENERIC_PANEL_ATTEMPT_TYPE


class AttemptConfigSource(Protocol):
    id: str
    configuration_snapshot: dict[str, Any]
    input_snapshot: dict[str, Any]


def panel_config_from_attempt(
    attempt: AttemptConfigSource,
    *,
    module: str,
    title: str,
) -> PanelSessionConfig:
    raw: dict[str, Any] = dict(attempt.configuration_snapshot or {})
    nested = raw.get("panel")
    if isinstance(nested, dict):
        raw = dict(nested)
    incoming = attempt.input_snapshot if isinstance(attempt.input_snapshot, dict) else {}
    if not str(raw.get("topic") or "").strip():
        topic = incoming.get("topic") or incoming.get("question") or title
        raw["topic"] = topic
    if not str(raw.get("brief") or "").strip() and incoming.get("brief"):
        raw["brief"] = incoming["brief"]
    raw.setdefault("protocol", "generic_panel")
    raw.setdefault("module", module)
    config = PanelSessionConfig.model_validate(raw)
    if config.protocol != "generic_panel":
        raise ExecutionStatusError(
            f"Attempt {attempt.id} configuration protocol {config.protocol!r} "
            "is not generic_panel"
        )
    if not config.expert_slots:
        raise ExecutionError(
            f"Attempt {attempt.id} configuration_snapshot must include expert_slots"
        )
    return config


def validate_generic_panel_snapshots(
    *,
    configuration_snapshot: dict[str, Any],
    input_snapshot: dict[str, Any],
    module: str,
    title: str,
) -> PanelSessionConfig:
    """Fail closed at the HTTP boundary before an Attempt is persisted."""
    probe = SimpleNamespace(
        id="new",
        configuration_snapshot=configuration_snapshot,
        input_snapshot=input_snapshot,
    )
    return panel_config_from_attempt(probe, module=module, title=title)


def _result_from_row(
    attempt: ExecutionAttempt,
    row: ExecutionAttemptResult | None,
) -> AttemptPanelResult:
    panel_result = None
    if row is not None:
        panel_result = PanelResult.model_validate(row.payload)
    return AttemptPanelResult(
        attempt_id=attempt.id,
        evidence_set_id=attempt.evidence_set_id,
        status=attempt.status,
        result_id=None if row is None else row.id,
        panel_session_id=None if row is None else row.panel_session_id,
        panel_result=panel_result,
    )


async def _existing_completed_result(
    session: AsyncSession,
    attempt: ExecutionAttempt,
) -> AttemptPanelResult:
    row = await get_attempt_result(session, attempt.id)
    if row is None:
        raise ExecutionStatusError(
            f"Attempt {attempt.id} is completed but has no persisted panel result"
        )
    return _result_from_row(attempt, row)


def _evidence_prompt(prompts: dict[str, str], rendered: RenderedEvidence) -> str:
    return render_prompt(
        prompts, "panel.evidence.instructions", evidence=rendered.prompt_body
    )


async def _fail_claimed_panel(session: AsyncSession, attempt_id: str) -> None:
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "running":
        await fail_attempt(session, attempt_id)
    await session.commit()


async def execute_generic_panel_attempt(
    session: AsyncSession,
    *,
    attempt_id: str,
    prompts: dict[str, str],
    run_panel: PanelRunner | None = None,
) -> AttemptPanelResult:
    """Run generic_panel against a ready Attempt's frozen EvidenceSet.

    Scope and evidence always come from the Attempt/Run. Does not execute
    ResearchRouter or mutate a frozen EvidenceSet. Competency is still gated
    before raise-hand; evidence cannot manufacture expertise.
    """
    runner = run_panel or run_generic_panel
    attempt = await get_attempt(session, attempt_id)
    if attempt.status == "completed":
        return await _existing_completed_result(session, attempt)
    if attempt.status == "running":
        raise ExecutionStatusError(
            f"Attempt {attempt.id} panel execution is already in progress"
        )
    if attempt.status == "failed":
        raise ExecutionStatusError(
            f"Attempt {attempt.id} failed; retry requires a new Attempt"
        )
    if attempt.status != "ready":
        raise ExecutionStatusError(
            f"Cannot start panel execution on attempt {attempt.id} "
            f"with status={attempt.status}"
        )
    if not _compatible_attempt_type(attempt.attempt_type):
        raise ExecutionStatusError(
            f"Attempt {attempt.id} type {attempt.attempt_type!r} is not "
            "compatible with generic_panel"
        )

    run = await get_run(session, attempt.run_id)
    evidence_set = await require_frozen_evidence_for_attempt(session, attempt)
    items = await list_evidence_items(session, evidence_set.id)
    rendered = render_frozen_evidence(items)
    config = panel_config_from_attempt(attempt, module=run.module, title=run.title)
    evidence_prompt = _evidence_prompt(prompts, rendered)
    allowed_refs = frozenset(rendered.refs)

    claimed = False
    panel_session_id: str | None = None
    try:
        attempt = await claim_attempt_running(session, attempt_id)
        if attempt.status == "completed":
            return await _existing_completed_result(session, attempt)
        claimed = True
        created = await create_panel_session(
            session, PanelSessionCreate(config=config)
        )
        panel_session_id = created.id
        panel = await get_panel_session(session, created.id)
        if panel is None:
            raise PanelAttemptError(f"Panel session {created.id} was not created")
        panel.status = "running"
        await session.flush()
        await session.commit()

        panel = await get_panel_session(session, created.id)
        if panel is None:
            raise PanelAttemptError(f"Panel session {created.id} was not created")
        panel = await runner(
            session,
            panel,
            prompts,
            frozen_evidence=True,
            evidence_prompt=evidence_prompt,
            allowed_evidence_refs=allowed_refs,
        )
        if not panel.result:
            raise PanelAttemptError(
                f"generic_panel produced no result for attempt {attempt_id}"
            )
        panel_result = PanelResult.model_validate(panel.result)
        stored = await persist_attempt_result(
            session,
            attempt_id=attempt_id,
            result_type=GENERIC_PANEL_RESULT_TYPE,
            schema_version=GENERIC_PANEL_RESULT_SCHEMA,
            payload=panel_result.model_dump(mode="json"),
            evidence_refs=rendered.mapping(),
            panel_session_id=panel.id,
        )
        attempt = await complete_attempt(session, attempt_id)
        await session.commit()
        return _result_from_row(attempt, stored)
    except BaseException as exc:
        if isinstance(exc, ExecutionStatusError) and not claimed:
            raise
        await session.rollback()
        if claimed:
            if panel_session_id is not None:
                panel = await get_panel_session(session, panel_session_id)
                if panel is not None and panel.status != "succeeded":
                    panel.status = "failed"
                    panel.error = str(exc)[:2000]
            await _fail_claimed_panel(session, attempt_id)
        if isinstance(exc, Exception):
            raise PanelAttemptError(
                f"Attempt {attempt_id} generic_panel failed"
            ) from exc
        raise
