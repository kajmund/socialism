"""Bridge Expertgranskning sessions to the durable execution research domain."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PanelSession
from app.services.execution.service import create_attempt, create_run, get_attempt
from app.services.panel.attempt_execution import execute_generic_panel_attempt
from app.services.panel.schemas import PanelSessionConfig
from app.services.prompt_store import require_active_prompts
from app.services.research.planner import ResearchObjective, research_objective_to_snapshot
from app.services.research_worker import accept_attempt_research, run_research_claim

from . import MODULE_ID
from .sessions import document_text_from_config, review_intent_from_config

_RESUMABLE_RESEARCH_STATUSES = frozenset({"created", "researching", "ready"})


def _research_objective(config: PanelSessionConfig) -> str:
    intent = config.review_intent.strip()
    suffix = f" Granskningssyfte: {intent}" if intent else ""
    return (
        "Identifiera och inhämta det externa underlag som behövs för att "
        f"expertgranska dokumentet {config.topic!r}.{suffix}"
    )


def _research_context(config: PanelSessionConfig) -> dict[str, Any]:
    return {
        "topic": config.topic,
        "review_intent": config.review_intent,
        "document": config.brief,
        "experts": [
            {
                "id": slot.slot_id,
                "label": slot.label,
                "profile": slot.profile,
            }
            for slot in config.expert_slots
        ],
    }


async def _resolve_execution_attempt(
    session: AsyncSession,
    *,
    panel: PanelSession,
    config: PanelSessionConfig,
    customer_id: int,
) -> tuple[str, bool]:
    """Return attempt id and whether research must still run."""
    stored = panel.config if isinstance(panel.config, dict) else {}
    existing_id = str(stored.get("execution_attempt_id") or "").strip()
    if existing_id:
        existing = await get_attempt(session, existing_id)
        if existing is not None and existing.status in _RESUMABLE_RESEARCH_STATUSES:
            if existing.status in {"created", "researching"}:
                objective = ResearchObjective(
                    objective=_research_objective(config),
                    context=_research_context(config),
                )
                await accept_attempt_research(
                    session,
                    attempt_id=existing.id,
                    research_objective=objective.objective,
                    research_context=objective.context,
                    research_plan=None,
                    schedule=False,
                )
            return existing.id, existing.status != "ready"

    run = await create_run(
        session,
        customer_id=customer_id,
        module=MODULE_ID,
        title=config.topic,
        context={
            "consumer": "expertgranskning",
            "panel_session_id": panel.id,
        },
    )
    objective = ResearchObjective(
        objective=_research_objective(config),
        context=_research_context(config),
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=config.model_dump(mode="json"),
        input_snapshot={
            "topic": config.topic,
            "brief": document_text_from_config(stored),
            "review_intent": review_intent_from_config(stored),
        },
        research_objective_snapshot=research_objective_to_snapshot(objective),
    )
    stored_config = dict(stored)
    stored_config["execution_run_id"] = run.id
    stored_config["execution_attempt_id"] = attempt.id
    panel.config = stored_config
    await session.flush()
    await accept_attempt_research(
        session,
        attempt_id=attempt.id,
        research_objective=objective.objective,
        research_context=objective.context,
        research_plan=None,
        schedule=False,
    )
    return attempt.id, True


async def run_expertgranskning_with_research(
    factory: async_sessionmaker[AsyncSession],
    *,
    session_id: str,
    customer_id: int,
) -> str:
    """Research, freeze evidence, then run the existing panel session."""
    attempt_id: str
    needs_research: bool
    async with factory() as session:
        panel = await session.get(PanelSession, session_id)
        if panel is None:
            raise ValueError(f"Panel session not found: {session_id}")
        config = PanelSessionConfig.model_validate(panel.config or {})
        attempt_id, needs_research = await _resolve_execution_attempt(
            session,
            panel=panel,
            config=config,
            customer_id=customer_id,
        )

    if needs_research:
        await run_research_claim(attempt_id)

    async with factory() as session:
        attempt = await get_attempt(session, attempt_id)
        if attempt.status != "ready":
            raise RuntimeError(
                f"Expertgranskning research did not become ready: {attempt.status}"
            )
        prompts = await require_active_prompts(
            session,
            customer_id=customer_id,
            module=MODULE_ID,
            language="sv",
        )
        await execute_generic_panel_attempt(
            session,
            attempt_id=attempt_id,
            prompts=prompts,
            panel_session_id=session_id,
        )
    return attempt_id
