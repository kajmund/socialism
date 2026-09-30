"""Persist the expert chat question after canonical identity preparation."""

from __future__ import annotations
from typing import TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import (
    Job,
    Persona,
    ExecutionRun,
    ExecutionAttempt,
    SpecificQuestion,
    ResearchQuestion,
)
from app.services.research.question_graph import QuestionEvidenceGraph

if TYPE_CHECKING:
    from app.services.expert_chat_research import ExpertChatResearchJobRequest

from app.services.execution import create_run, create_attempt
from app.services.research.question_domain import (
    create_specific_question,
    create_general_question,
    GeneralQuestionDraft,
)


async def create_chat_question(
    session: AsyncSession,
    *,
    job: Job,
    persona: Persona,
    payload: ExpertChatResearchJobRequest,
    graph: QuestionEvidenceGraph,
) -> tuple[ExecutionRun, ExecutionAttempt, SpecificQuestion, ResearchQuestion]:
    run = await create_run(
        session,
        customer_id=job.customer_id,
        module="dd",
        title=payload.specific_question,
        context={
            "consumer": "expert_chat",
            "persona_id": persona.id,
            "job_id": job.id,
        },
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="expert_chat_question_dag",
        configuration_snapshot={"persona_id": persona.id},
        input_snapshot={
            "specific_question": payload.specific_question,
            "question": payload.question,
        },
    )
    specific = await create_specific_question(
        session,
        run_id=run.id,
        text=payload.specific_question,
        context={"persona_id": persona.id, "job_id": job.id},
        origin_kind="expert_chat",
        origin_ref=job.id,
    )
    question = await create_general_question(
        session,
        attempt_id=attempt.id,
        specific_question_id=specific.id,
        question_graph=graph,
        draft=GeneralQuestionDraft(
            question=payload.question,
            why_needed="Expertchatten saknar tillräckligt fryst evidens för frågan.",
            raised_by_expert_ids=[persona.id],
        ),
    )
    return run, attempt, specific, question
