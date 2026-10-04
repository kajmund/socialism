"""Project the existing durable workspace research jobs into voice canvases."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExecutionAttempt, ExecutionRun, Job, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceOperation, WorkspaceResearch
from app.services.workspace.containers import require_container


def job_bound_to_canvas(job: Job, canvas: VoiceWorkspace) -> bool:
    request = job.request or {}
    return (job.customer_id == canvas.customer_id
            and request.get("voice_workspace_id") == canvas.id
            and request.get("workspace_id") == canvas.workspace_id
            and request.get("chat_id") == canvas.chat_id
            and request.get("owner_user_id") == canvas.owner_user_id)


async def sync_research_links(session: AsyncSession, canvas: VoiceWorkspace) -> list[dict]:
    user = await session.get(UserAccount, canvas.owner_user_id)
    await require_container(session, canvas, user)
    jobs = list(await session.scalars(select(Job).join(WorkspaceOperation, WorkspaceOperation.job_id == Job.id)
        .where(WorkspaceOperation.workspace_id == canvas.id, WorkspaceOperation.tool_name == "start_research")
        .order_by(Job.created_at)))
    result = []
    for job in jobs:
        if not job_bound_to_canvas(job, canvas) or job.kind != "workspace_research":
            raise HTTPException(status_code=404, detail="workspace_research_not_found")
        attempt_id = (job.result or {}).get("attempt_id")
        attempt = await _validated_attempt(session, canvas, job, attempt_id) if attempt_id else None
        result.append({"job_id": job.id, "attempt_id": attempt.id if attempt else None,
                       "run_id": attempt.run_id if attempt else None,
                       "status": attempt.status if attempt else job.status,
                       "progress_url": f"/jobs/{job.id}"})
    await session.flush()
    return result


async def _validated_attempt(session: AsyncSession, canvas: VoiceWorkspace, job: Job, attempt_id: str) -> ExecutionAttempt:
    attempt = await session.get(ExecutionAttempt, attempt_id)
    run = await session.get(ExecutionRun, attempt.run_id) if attempt else None
    if (run is None or run.customer_id != canvas.customer_id or run.module != canvas.module
            or run.context.get("job_id") != job.id or run.context.get("workspace_id") != canvas.workspace_id
            or run.context.get("chat_id") != canvas.chat_id or run.context.get("owner_user_id") != canvas.owner_user_id):
        raise HTTPException(status_code=404, detail="workspace_research_not_found")
    if await session.get(WorkspaceResearch, (canvas.id, attempt.id)) is None:
        session.add(WorkspaceResearch(workspace_id=canvas.id, attempt_id=attempt.id))
    return attempt
