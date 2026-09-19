"""Background research initiated by an explicitly confirmed expert-chat tool call."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ExecutionAttempt, Job, Persona
from app.serializers import utcnow
from app.services.execution.service import create_attempt, create_run, get_attempt, get_run
from app.services.panel.question_expert_adapters import (
    PanelCompetencyQuestionMatcher,
    UnderlagExpertCreator,
)
from app.services.prompt_store import require_active_prompts
from app.services.research.composition import (
    build_standard_question_graph,
    build_standard_research_router,
)
from app.services.research.expert_knowledge import (
    publish_completed_attempt_knowledge,
    remember_published_question,
)
from app.services.research.question_attempt_worker import AttemptResearchQuestionWorker
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from app.services.research.question_execution import (
    execute_research_question_dag,
    requeue_interrupted_research_questions,
)
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


def _result_id(result: dict[str, object], key: str) -> str | None:
    value = result.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _existing_research_attempt(session: AsyncSession, job: Job) -> ExecutionAttempt | None:
    result = job.result if isinstance(job.result, dict) else {}
    attempt_id = _result_id(result, "attempt_id") or _result_id(result, "execution_attempt_id")
    if attempt_id is None:
        return None
    attempt = await get_attempt(session, attempt_id)
    run = await get_run(session, attempt.run_id)
    context = run.context if isinstance(run.context, dict) else {}
    if (
        run.customer_id != job.customer_id
        or attempt.attempt_type != "expert_chat_question_dag"
        or context.get("consumer") != "expert_chat"
        or context.get("job_id") != job.id
    ):
        raise RuntimeError(f"Expert chat research Attempt is outside job scope: {attempt.id}")
    return attempt


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
        if persona is None or persona.customer_id != job.customer_id or persona.kind != "expert":
            raise ValueError("Expert not found for research job")
        prompts = await require_active_prompts(
            session,
            customer_id=job.customer_id,
            module="dd",
            language="sv",
        )
        attempt = await _existing_research_attempt(session, job)
        if attempt is not None:
            await requeue_interrupted_research_questions(session, attempt_id=attempt.id)
            result = dict(job.result) if isinstance(job.result, dict) else {}
            run_id = attempt.run_id
            attempt_id = attempt.id
            specific_id = _result_id(result, "specific_question_id")
            question_id = _result_id(result, "research_question_id")
            if specific_id is None or question_id is None:
                raise RuntimeError(f"Expert chat research job is missing question ids: {job.id}")
        else:
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
            job.result = {
                **(dict(job.result) if isinstance(job.result, dict) else {}),
                "run_id": run.id,
                "attempt_id": attempt.id,
                "specific_question_id": specific.id,
                "research_question_id": question.id,
            }
            job.updated_at = utcnow()
            run_id = run.id
            attempt_id = attempt.id
            specific_id = specific.id
            question_id = question.id
        components = await bind_research_components(
            session,
            customer_id=job.customer_id,
            module="dd",
        )
        research_planner = components["research_planner"]
        if research_planner is None:
            raise RuntimeError("Research planner is required for expert chat")
        await session.commit()
        await session.refresh(job)
        # Lazy import: jobs.py imports this module from its worker dispatch.
        from app.services.jobs import publish_job

        await publish_job(job)

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
    if result.status not in {"completed", "completed_with_gaps"}:
        raise RuntimeError(f"Expert chat research stopped as {result.status}")
    async with factory() as session:
        memories = await publish_completed_attempt_knowledge(
            session,
            attempt_id=attempt_id,
            graph=build_standard_question_graph(),
        )
        await session.commit()
    await remember_published_question(memories)
    return {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "specific_question_id": specific_id,
        "research_question_id": question_id,
        "completed_questions": result.completed_count,
        "failed_questions": result.failed_count,
        "blocked_questions": result.blocked_count,
    }
