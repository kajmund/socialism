"""Expert-chat research job creates once and resumes the same Attempt."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.database.models import ExecutionAttempt, Job, Persona, ResearchQuestion
from app.serializers import utcnow
from app.services.execution import create_attempt, create_run
from app.services.expert_chat_research import run_expert_chat_research_job
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from tests.conftest import TEST_CUSTOMER_ID


async def _seed_job(session, *, with_attempt: bool):
    expert = Persona(
        id="expert-chat-resume",
        customer_id=TEST_CUSTOMER_ID,
        kind="expert",
        name="Avtalsjuristen",
        age=None,
        occ="Jurist",
        district="—",
        quote="",
        origin="test",
        profile={},
        tools=None,
    )
    session.add(expert)
    now = utcnow()
    job = Job(
        id="job-chat-resume",
        customer_id=TEST_CUSTOMER_ID,
        kind="expert_chat_research",
        status="running",
        label="Expertresearch: Klausul 2",
        request={
            "persona_id": expert.id,
            "specific_question": "Vad innebär klausul 2?",
            "question": "Vilka rekvisit gäller?",
        },
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    attempt_id = None
    question_id = None
    if with_attempt:
        run = await create_run(
            session,
            customer_id=TEST_CUSTOMER_ID,
            module="dd",
            title="Vad innebär klausul 2?",
            context={
                "consumer": "expert_chat",
                "persona_id": expert.id,
                "job_id": job.id,
            },
        )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="expert_chat_question_dag",
            configuration_snapshot={"persona_id": expert.id},
            input_snapshot={
                "specific_question": "Vad innebär klausul 2?",
                "question": "Vilka rekvisit gäller?",
            },
        )
        specific = await create_specific_question(
            session,
            run_id=run.id,
            text="Vad innebär klausul 2?",
            context={"persona_id": expert.id, "job_id": job.id},
            origin_kind="expert_chat",
            origin_ref=job.id,
        )
        question = await create_general_question(
            session,
            attempt_id=attempt.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(
                question="Vilka rekvisit gäller?",
                raised_by_expert_ids=[expert.id],
            ),
        )
        question.status = "running"
        job.result = {
            "run_id": run.id,
            "attempt_id": attempt.id,
            "specific_question_id": specific.id,
            "research_question_id": question.id,
        }
        attempt_id = attempt.id
        question_id = question.id
    await session.commit()
    return attempt_id, question_id


@pytest.mark.asyncio
async def test_resume_reuses_attempt_and_requeues_running_question(client_db, monkeypatch):
    _client, factory = client_db
    async with factory() as session:
        attempt_id, question_id = await _seed_job(session, with_attempt=True)

    monkeypatch.setattr(
        "app.services.expert_chat_research.require_active_prompts",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "app.services.expert_chat_research.bind_research_components",
        AsyncMock(
            return_value={
                "research_planner": object(),
                "assessor": None,
                "planner": None,
                "completeness_reviewer": None,
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.expert_chat_research.assign_unowned_research_questions",
        AsyncMock(side_effect=AssertionError("resume must not replan questions")),
    )
    create_run = AsyncMock(side_effect=AssertionError("resume must not create a new run"))
    monkeypatch.setattr("app.services.expert_chat_research.create_run", create_run)

    async def assert_requeued(_factory, *, attempt_id: str, worker):
        async with factory() as session:
            question = await session.get(ResearchQuestion, question_id)
            assert question is not None
            assert question.status == "pending"
        return SimpleNamespace(status="completed", completed_count=1, failed_count=0, blocked_count=0)

    monkeypatch.setattr(
        "app.services.expert_chat_research.execute_research_question_dag",
        assert_requeued,
    )
    monkeypatch.setattr(
        "app.services.expert_chat_research.publish_completed_attempt_knowledge",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.expert_chat_research.remember_published_question",
        AsyncMock(),
    )

    result = await run_expert_chat_research_job(factory, job_id="job-chat-resume")
    assert result["attempt_id"] == attempt_id
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(ExecutionAttempt))
    assert count == 1
