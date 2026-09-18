"""Expertgranskning retries reuse persisted research and frozen evidence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExecutionAttempt, PanelSession, ResearchQuestion
from app.services.execution import (
    add_evidence_items,
    create_attempt,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    mark_ready,
)
from app.services.expertgranskning import MODULE_ID
from app.services.expertgranskning.execution import run_expertgranskning_with_research
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
from app.services.research.models import research_evidence
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from tests.conftest import TEST_CUSTOMER_ID


def _panel_config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        module=MODULE_ID,
        topic="Höstens kampanjlinje",
        brief="Detta PM föreslår en ny kommunikationslinje.",
        max_rounds=1,
        research_before_review=True,
        expert_slots=[
            PanelExpertSlot(slot_id="legal", label="Jurist", profile="Avtalsrätt"),
        ],
    )


async def _ready_attempt(session: AsyncSession, *, panel_id: str) -> tuple[str, str]:
    run = await create_run(
        session,
        customer_id=TEST_CUSTOMER_ID,
        module=MODULE_ID,
        title="Höstens kampanjlinje",
        context={"consumer": "expertgranskning", "panel_session_id": panel_id},
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await add_evidence_items(
        session,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="research_1",
                source_type="customer_knowledge",
                status="found",
                title="Kundunderlag",
                excerpt="Relevant bakgrund för dokumentgranskningen.",
                provider="test",
            )
        ],
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    config = _panel_config()
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=config.model_dump(mode="json"),
        input_snapshot={"topic": config.topic, "brief": config.brief},
        evidence_set_id=frozen.id,
    )
    await mark_ready(session, attempt.id)
    await session.commit()
    return run.id, attempt.id


async def test_expertgranskning_resumes_ready_attempt_without_research(
    client_db,
    monkeypatch,
):
    _client, factory = client_db
    panel_id = "eg-resume-ready"
    async with factory() as session:
        run_id, attempt_id = await _ready_attempt(session, panel_id=panel_id)
        config = _panel_config()
        session.add(
            PanelSession(
                id=panel_id,
                protocol="generic_panel",
                status="failed",
                config={
                    **config.model_dump(mode="json"),
                    "execution_run_id": run_id,
                    "execution_attempt_id": attempt_id,
                },
            )
        )
        await session.commit()

    plan_questions = AsyncMock(side_effect=AssertionError("research was replanned"))
    execute_dag = AsyncMock(side_effect=AssertionError("research DAG was rerun"))
    freeze_evidence = AsyncMock(side_effect=AssertionError("evidence was frozen again"))
    bind_components = AsyncMock(side_effect=AssertionError("research components were rebound"))
    execute_panel = AsyncMock()
    monkeypatch.setattr(
        "app.services.expertgranskning.execution.require_active_prompts",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution._plan_questions",
        plan_questions,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution.execute_research_question_dag",
        execute_dag,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution._freeze_aggregate_evidence",
        freeze_evidence,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution.bind_research_components",
        bind_components,
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution.execute_generic_panel_attempt",
        execute_panel,
    )

    result_id = await run_expertgranskning_with_research(
        factory,
        session_id=panel_id,
        customer_id=TEST_CUSTOMER_ID,
    )

    assert result_id == attempt_id
    plan_questions.assert_not_awaited()
    execute_dag.assert_not_awaited()
    freeze_evidence.assert_not_awaited()
    bind_components.assert_not_awaited()
    execute_panel.assert_awaited_once()
    assert execute_panel.await_args.kwargs["attempt_id"] == attempt_id
    async with factory() as session:
        attempt_count = await session.scalar(select(func.count()).select_from(ExecutionAttempt))
    assert attempt_count == 1


async def test_expertgranskning_retry_requeues_interrupted_question_on_same_attempt(
    client_db,
    monkeypatch,
):
    _client, factory = client_db
    panel_id = "eg-resume-created"
    config = _panel_config()
    async with factory() as session:
        run = await create_run(
            session,
            customer_id=TEST_CUSTOMER_ID,
            module=MODULE_ID,
            title=config.topic,
            context={"consumer": "expertgranskning", "panel_session_id": panel_id},
        )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="generic_panel",
            configuration_snapshot=config.model_dump(mode="json"),
            input_snapshot={"topic": config.topic, "brief": config.brief},
        )
        specific = await create_specific_question(
            session,
            run_id=run.id,
            text="Vad behöver granskas?",
            context={},
            origin_kind="expertgranskning",
            origin_ref=panel_id,
        )
        question = await create_general_question(
            session,
            attempt_id=attempt.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(question="Vilka rekvisit gäller?"),
        )
        question.status = "running"
        session.add(
            PanelSession(
                id=panel_id,
                protocol="generic_panel",
                status="failed",
                config={
                    **config.model_dump(mode="json"),
                    "execution_run_id": run.id,
                    "execution_attempt_id": attempt.id,
                },
            )
        )
        await session.commit()
        attempt_id = attempt.id
        question_id = question.id

    monkeypatch.setattr(
        "app.services.expertgranskning.execution.require_active_prompts",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution._plan_questions",
        AsyncMock(side_effect=AssertionError("research was replanned")),
    )
    monkeypatch.setattr(
        "app.services.expertgranskning.execution.bind_research_components",
        AsyncMock(
            return_value={
                "research_planner": object(),
                "assessor": None,
                "planner": None,
                "completeness_reviewer": None,
            }
        ),
    )

    async def assert_requeued(_factory, *, attempt_id: str, worker):
        async with factory() as session:
            question = await session.get(ResearchQuestion, question_id)
            assert question is not None
            assert question.status == "pending"
        return SimpleNamespace(status="waiting_for_assignment")

    monkeypatch.setattr(
        "app.services.expertgranskning.execution.execute_research_question_dag",
        assert_requeued,
    )

    try:
        await run_expertgranskning_with_research(
            factory,
            session_id=panel_id,
            customer_id=TEST_CUSTOMER_ID,
        )
    except RuntimeError as exc:
        assert "waiting_for_assignment" in str(exc)
    else:
        raise AssertionError("resumed incomplete DAG unexpectedly completed")

    async with factory() as session:
        attempts = list((await session.execute(select(ExecutionAttempt))).scalars())
    assert [attempt.id for attempt in attempts] == [attempt_id]


async def test_expertgranskning_rejects_persisted_attempt_from_another_panel(
    client_db,
    monkeypatch,
):
    _client, factory = client_db
    async with factory() as session:
        run_id, attempt_id = await _ready_attempt(session, panel_id="original-panel")
        config = _panel_config()
        session.add(
            PanelSession(
                id="other-panel",
                protocol="generic_panel",
                status="failed",
                config={
                    **config.model_dump(mode="json"),
                    "execution_run_id": run_id,
                    "execution_attempt_id": attempt_id,
                },
            )
        )
        await session.commit()

    monkeypatch.setattr(
        "app.services.expertgranskning.execution.require_active_prompts",
        AsyncMock(return_value={}),
    )

    try:
        await run_expertgranskning_with_research(
            factory,
            session_id="other-panel",
            customer_id=TEST_CUSTOMER_ID,
        )
    except RuntimeError as exc:
        assert "outside panel scope" in str(exc)
    else:
        raise AssertionError("cross-panel Attempt reuse was accepted")
