"""Background research initiated by an explicitly confirmed expert-chat tool call."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Job, Persona
from app.services.execution.service import create_attempt, create_run
from app.services.panel.question_expert_adapters import (
    PanelCompetencyQuestionMatcher,
    UnderlagExpertCreator,
)
from app.services.prompt_store import require_active_prompts
from app.services.research.composition import build_standard_research_router
from app.services.research.question_attempt_worker import AttemptResearchQuestionWorker
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from app.services.research.question_execution import execute_research_question_dag
from app.services.research.question_expert_assignment import (
    assign_unowned_research_questions,
)
from app.services.research_worker import bind_research_components

JOB_KIND = "expert_chat_research"


class ExpertChatResearchJobRequest(BaseModel):
    persona_id: str = Field(min_length=1, max_length=64)
    specific_question: str = Field(min_length=1, max_length=4000)
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("persona_id", "specific_question", "question", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        return str(value or "").strip()


async def run_expert_chat_research_job(
    factory: async_sessionmaker[AsyncSession],
    *,
    job_id: str,
) -> dict[str, object]:
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        payload = ExpertChatResearchJobRequest.model_validate(job.request or {})
        persona = await session.get(Persona, payload.persona_id)
        if (
            persona is None
            or persona.customer_id != job.customer_id
            or persona.kind != "expert"
        ):
            raise ValueError("Expert not found for research job")
        prompts = await require_active_prompts(
            session,
            customer_id=job.customer_id,
            module="dd",
            language="sv",
        )
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
            draft=GeneralQuestionDraft(
                question=payload.question,
                why_needed="Expertchatten saknar tillräckligt fryst evidens för frågan.",
                raised_by_expert_ids=[persona.id],
            ),
        )
        await assign_unowned_research_questions(
            session,
            attempt_id=attempt.id,
            matcher=PanelCompetencyQuestionMatcher(prompts=prompts, locale="sv"),
            creator=UnderlagExpertCreator(prompts=prompts, language="sv"),
        )
        components = await bind_research_components(
            session,
            customer_id=job.customer_id,
            module="dd",
        )
        research_planner = components["research_planner"]
        if research_planner is None:
            raise RuntimeError("Research planner is required for expert chat")
        await session.commit()
        attempt_id = attempt.id
        run_id = run.id
        specific_id = specific.id
        question_id = question.id

    worker = AttemptResearchQuestionWorker(
        session_factory=factory,
        router_factory=build_standard_research_router,
        research_planner=research_planner,
        assessor=components["assessor"],
        follow_up_planner=components["planner"],
        completeness_reviewer=components["completeness_reviewer"],
    )
    result = await execute_research_question_dag(
        factory,
        attempt_id=attempt_id,
        worker=worker,
    )
    if result.status != "completed":
        raise RuntimeError(f"Expert chat research stopped as {result.status}")
    return {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "specific_question_id": specific_id,
        "research_question_id": question_id,
        "completed_questions": result.completed_count,
    }
