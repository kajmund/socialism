"""Workspace chat uploads, questions, and original source passages."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    Job,
    TextUnitRecord,
    UserAccount,
)
from app.database.session import get_session
from app.database.workspaces import WorkspaceChat, WorkspaceChatMessage
from app.schemas.domain import JobCreate, JobOut
from app.schemas.workspace_chat import (
    WorkspaceChatCreate,
    WorkspaceChatMessageWrite,
    WorkspaceChatOut,
    WorkspaceResearchRequest,
)
from app.services import jobs as jobs_service
from app.services.object_storage import MAX_UNDERLAG_BYTES, ObjectStorageError, get_object
from app.services.stored_objects import serialize_underlag, upload_underlag
from app.services.underlag_schemas import UnderlagOut
from app.services.workspace_chat_turn import workspace_chat_turn
from app.services.workspace_chats import (
    create_chat,
    list_chat_files,
    require_chat,
    require_chat_file,
    serialize_chat,
)
from app.services.workspace_research_start import JOB_KIND, queue_workspace_research
from app.services.workspaces import require_workspace_customer, resolve_workspace

router = APIRouter(prefix="/workspace-chats", tags=["workspace-chats"])


@router.post("", response_model=WorkspaceChatOut, status_code=201)
async def post_chat(
    body: WorkspaceChatCreate,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await create_chat(session, user, body, customer_id)
    await session.commit()
    return await serialize_chat(session, chat)


@router.get("", response_model=list[WorkspaceChatOut])
async def get_chats(
    workspace_id: str | None = None,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    customer = await require_workspace_customer(session, user, customer_id)
    workspace = await resolve_workspace(
        session, customer_id=customer, user_id=user.id, workspace_id=workspace_id
    )
    chats = list(
        await session.scalars(
            select(WorkspaceChat)
            .where(
                WorkspaceChat.customer_id == customer,
                WorkspaceChat.workspace_id == workspace.id,
                WorkspaceChat.owner_user_id == user.id,
            )
            .order_by(WorkspaceChat.created_at.desc())
        )
    )
    await session.commit()
    return [await serialize_chat(session, chat) for chat in chats]


@router.get("/{chat_id}", response_model=WorkspaceChatOut)
async def get_chat(
    chat_id: str,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    return await serialize_chat(session, await require_chat(session, user, chat_id, customer_id))


@router.post("/{chat_id}/messages", response_model=WorkspaceChatOut)
async def post_message(
    chat_id: str,
    *,
    body: WorkspaceChatMessageWrite,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await workspace_chat_turn(session, user, chat_id, body.content, customer_id=customer_id)
    return await serialize_chat(session, chat)


@router.get("/{chat_id}/files", response_model=list[UnderlagOut])
async def get_files(
    chat_id: str,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await require_chat(session, user, chat_id, customer_id)
    return [
        UnderlagOut(**serialize_underlag(row, include_text=False))
        for row in await list_chat_files(session, user, chat)
    ]


@router.post("/{chat_id}/files", response_model=UnderlagOut, status_code=201)
async def post_file(
    chat_id: str,
    *,
    file: UploadFile = File(...),
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await require_chat(session, user, chat_id, customer_id)
    actor_id, workspace_id, module, customer = (
        user.id,
        chat.workspace_id,
        chat.module,
        chat.customer_id,
    )
    await session.commit()
    data = await file.read(MAX_UNDERLAG_BYTES + 1)
    try:
        source = await upload_underlag(
            session,
            customer_id=customer,
            owner_user_id=actor_id,
            module=module,
            filename=file.filename or "file",
            content_type=file.content_type or "application/octet-stream",
            data=data,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ObjectStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    job = await jobs_service.create_job(
        session,
        JobCreate(
            kind="document_ingest",
            label=source.filename[:120],
            request={
                "object_id": source.id,
                "owner_user_id": actor_id,
                "workspace_id": workspace_id,
            },
        ),
    )
    source.knowledge_job_id = job.id
    session.add(
        WorkspaceChatMessage(
            chat_id=chat_id, role="user", content=source.filename, attachment_object_id=source.id
        )
    )
    await session.commit()
    jobs_service.enqueue_job(job.id)
    return UnderlagOut(**serialize_underlag(source, include_text=False))


@router.get("/{chat_id}/files/{object_id}")
async def get_file(
    chat_id: str,
    object_id: str,
    *,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await require_chat(session, user, chat_id, customer_id)
    source = await require_chat_file(session, user, chat, object_id)
    bucket, key = source.bucket, source.object_key
    await session.rollback()
    data, content_type = await get_object(bucket, key)
    return Response(content=data, media_type=content_type)


@router.post("/{chat_id}/research", response_model=JobOut, status_code=202)
async def post_research(
    chat_id: str,
    *,
    body: WorkspaceResearchRequest,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await require_chat(session, user, chat_id, customer_id)
    return jobs_service.serialize_job(await queue_workspace_research(session, user, chat, body))


@router.get("/{chat_id}/research", response_model=list[JobOut])
async def get_research(
    chat_id: str,
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await require_chat(session, user, chat_id, customer_id)
    jobs = list(
        await session.scalars(
            select(Job)
            .where(
                Job.customer_id == chat.customer_id,
                Job.kind == JOB_KIND,
            )
            .order_by(Job.created_at.desc())
        )
    )
    return [
        jobs_service.serialize_job(job) for job in jobs if job.request.get("chat_id") == chat.id
    ]


@router.get("/{chat_id}/sources/{object_id}")
async def get_source(
    chat_id: str,
    object_id: str,
    *,
    text_unit_id: str = Query(...),
    document_version_id: str = Query(...),
    customer_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
):
    chat = await require_chat(session, user, chat_id, customer_id)
    source = await require_chat_file(session, user, chat, object_id)
    unit = await session.get(TextUnitRecord, text_unit_id)
    version = await session.get(DocumentVersionRecord, document_version_id)
    document = await session.get(CanonicalDocumentRecord, unit.document_id) if unit else None
    if (
        unit is None
        or version is None
        or document is None
        or unit.document_version_id != version.id
        or version.document_id != document.id
        or document.source_object_id != source.id
        or unit.customer_id != chat.customer_id
        or document.customer_id != chat.customer_id
        or version.customer_id != chat.customer_id
    ):
        raise HTTPException(status_code=404, detail="source_passage_not_found")
    return {
        "source_object_id": source.id,
        "document_version_id": version.id,
        "text_unit_id": unit.id,
        "filename": source.filename,
        "locator": unit.locator,
        "excerpt": unit.text,
        "workspace_id": source.workspace_id,
        "file_url": f"/workspace-chats/{chat.id}/files/{source.id}"
        if version.superseded_at is None
        else None,
    }
