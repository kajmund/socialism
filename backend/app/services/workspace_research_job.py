"""Workspace research uses the existing Attempt research engine."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Job, UserAccount
from app.services.execution.service import create_attempt, create_run, get_attempt, get_run
from app.services.research.composition import (
    build_standard_question_graph,
    build_standard_research_router,
)
from app.services.research.execution import execute_attempt_research
from app.services.research.planner import ResearchObjective
from app.services.research_worker import bind_research_components
from app.services.workspace_chats import require_chat
from app.services.workspace_research_answer import compose_research_answer
from app.services.knowledge.document_grounding import validate_manifest
from app.services.research.workspace_context import research_context_from_run


async def _prepare(session: AsyncSession, job_id: str) -> tuple[str, str, dict]:
    job = await session.get(Job, job_id)
    if job is None or job.kind != "workspace_research":
        raise ValueError("Workspace research job not found")
    request = dict(job.request)
    user = await session.get(UserAccount, request["owner_user_id"])
    chat = await require_chat(session, user, request["chat_id"], job.customer_id)
    if chat.workspace_id != request["workspace_id"]:
        raise ValueError("Research chat workspace changed")
    result = dict(job.result or {})
    if result.get("attempt_id"):
        attempt = await get_attempt(session, result["attempt_id"])
        run = await get_run(session, attempt.run_id)
        if (
            run.customer_id != job.customer_id
            or run.context.get("job_id") != job_id
            or run.context.get("consumer") != "workspace_chat"
            or any(
                run.context.get(key) != request.get(key)
                for key in (
                    "workspace_id",
                    "chat_id",
                    "document_manifest",
                    "readable_workspace_ids",
                    "question",
                    "owner_user_id",
                )
            )
        ):
            raise ValueError("Workspace research attempt crossed job scope")
    else:
        run = await create_run(
            session,
            customer_id=job.customer_id,
            module=chat.module,
            title=request["question"][:120],
            context={
                **request,
                "consumer": "workspace_chat",
                "job_id": job_id,
                "case_id": chat.workspace_id,
            },
        )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="workspace_research",
            input_snapshot={"document_manifest": request["document_manifest"]},
        )
        job.result = {"run_id": run.id, "attempt_id": attempt.id}
    attempt_id = attempt.id
    if attempt.status != "ready":
        await validate_manifest(session, research_context_from_run(run).scope)
    components = await bind_research_components(
        session, customer_id=job.customer_id, module=chat.module
    )
    await session.commit()
    return attempt_id, request["question"], components


async def run_workspace_research_job(
    factory: async_sessionmaker[AsyncSession], *, job_id: str
) -> dict:
    async with factory() as session:
        attempt_id, question, components = await _prepare(session, job_id)
        attempt = await get_attempt(session, attempt_id)
        status = attempt.status
        await session.rollback()
        if status != "ready":
            await execute_attempt_research(
                session,
                attempt_id=attempt_id,
                research_objective=ResearchObjective(objective=question),
                router_factory=build_standard_research_router,
                question_graph=build_standard_question_graph(),
                session_factory=factory,
                **components,
            )
        return await compose_research_answer(session, job_id, attempt_id)
