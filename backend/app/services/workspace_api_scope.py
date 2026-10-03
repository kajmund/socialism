"""Workspace checks for generic job and execution APIs."""

from collections.abc import Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import assert_job_owner_access, assert_kund_access, job_visible_to_user
from app.database.models import ExecutionAttempt, ExecutionRun, Job, StoredObject, UserAccount
from app.schemas.domain import JobCreate
from app.services import jobs as jobs_service
from app.services.execution.errors import ExecutionNotFoundError
from app.services.execution.service import get_attempt, get_run
from app.services.workspaces import resolve_readable_workspace_ids


async def require_context_workspace(
    session: AsyncSession,
    user: UserAccount,
    customer_id: int,
    context: Mapping,
) -> None:
    if "workspace_id" not in context:
        if any(field in context for field in ("document_manifest", "readable_workspace_ids")):
            raise HTTPException(status_code=422, detail="workspace_required_for_document_selection")
        return
    workspace_id = context["workspace_id"]
    if not isinstance(workspace_id, str) or not workspace_id:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    allowed = await resolve_readable_workspace_ids(
        session, customer_id=customer_id, user_id=user.id, workspace_id=workspace_id
    )
    _require_readable_context(context, workspace_id, set(allowed))


def _require_readable_context(context: Mapping, workspace_id: str, allowed: set[str]) -> None:
    readable = context.get("readable_workspace_ids", [workspace_id])
    if (
        not isinstance(readable, list)
        or not all(isinstance(value, str) for value in readable)
        or workspace_id not in readable
        or not set(readable).issubset(allowed)
    ):
        raise HTTPException(status_code=404, detail="workspace_not_found")
    manifest = context.get("document_manifest", [])
    if not isinstance(manifest, list) or any(
        not isinstance(row, dict) or row.get("workspace_id") not in readable for row in manifest
    ):
        raise HTTPException(status_code=404, detail="workspace_not_found")


async def require_job_scope(session: AsyncSession, user: UserAccount, job_id: str) -> Job:
    job = await jobs_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    assert_kund_access(user, job.customer_id)
    assert_job_owner_access(user, job)
    await require_context_workspace(session, user, job.customer_id, job.request or {})
    return job


async def visible_workspace_jobs(
    session: AsyncSession, user: UserAccount, jobs: list[Job]
) -> list[Job]:
    visible = []
    for job in jobs:
        if not job_visible_to_user(user, job):
            continue
        try:
            await require_context_workspace(session, user, job.customer_id, job.request or {})
        except HTTPException as exc:
            if exc.status_code not in (403, 404, 422):
                raise
            continue
        visible.append(job)
    return visible


async def archive_visible_workspace_jobs(
    session: AsyncSession, user: UserAccount, customer_id: int | None
) -> list[Job]:
    statement = select(Job).where(
        Job.status.in_(("succeeded", "failed")), Job.archived_at.is_(None)
    )
    if customer_id is not None:
        statement = statement.where(Job.customer_id == customer_id)
    candidates = list((await session.scalars(statement)).all())
    ids = {row.id for row in await visible_workspace_jobs(session, user, candidates)}
    return await jobs_service.archive_finished_jobs(
        session, customer_id=customer_id, include_job=lambda job: job.id in ids
    )


async def validate_new_workspace_job(
    session: AsyncSession, user: UserAccount, customer_id: int, body: JobCreate
) -> None:
    if body.kind == "document_ingest":
        source = await session.get(StoredObject, str(body.request.get("object_id") or ""))
        if source is None or source.customer_id != customer_id or source.owner_user_id != user.id:
            raise HTTPException(status_code=404, detail="File not found")
        if source.workspace_id is None:
            raise HTTPException(status_code=409, detail="document_workspace_missing")
        declared = body.request.get("workspace_id", source.workspace_id)
        if declared != source.workspace_id:
            raise HTTPException(status_code=404, detail="File not found")
        body.request["workspace_id"] = source.workspace_id
    await require_context_workspace(session, user, customer_id, body.request)


async def require_execution_run(
    session: AsyncSession, user: UserAccount, run_id: str
) -> ExecutionRun:
    try:
        run = await get_run(session, run_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert_kund_access(user, run.customer_id)
    await require_context_workspace(session, user, run.customer_id, run.context or {})
    return run


async def require_execution_attempt(
    session: AsyncSession, user: UserAccount, attempt_id: str
) -> tuple[ExecutionAttempt, ExecutionRun]:
    try:
        attempt = await get_attempt(session, attempt_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return attempt, await require_execution_run(session, user, attempt.run_id)


def scoped_research_context(run: ExecutionRun, context: dict) -> dict:
    owned = run.context or {}
    if "workspace_id" not in owned and "workspace_id" not in context:
        return dict(context)
    fields = (
        "workspace_id",
        "readable_workspace_ids",
        "document_manifest",
        "owner_user_id",
        "case_id",
    )
    for field in fields:
        if field in context and context[field] != owned.get(field):
            raise HTTPException(status_code=409, detail="research_workspace_scope_mismatch")
    return {**context, **{field: owned[field] for field in fields if field in owned}}
