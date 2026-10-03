"""Both modal and tool research freeze the same authorized document manifest."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Job, UserAccount
from app.database.workspaces import WorkspaceChat, WorkspaceChatMessage
from app.schemas.workspace_chat import WorkspaceResearchRequest
from app.serializers import utcnow
from app.services.workspace_chats import list_chat_files
from app.services.workspaces import resolve_readable_workspace_ids

JOB_KIND = "workspace_research"


async def document_manifest(
    session: AsyncSession,
    user: UserAccount,
    chat: WorkspaceChat,
    selected: list[str] | None,
) -> list[dict[str, str]]:
    visible = {row.id: row for row in await list_chat_files(session, user, chat)}
    ids = list(visible) if selected is None else list(dict.fromkeys(selected))
    if any(identity not in visible for identity in ids):
        raise HTTPException(status_code=404, detail="research_document_not_found")
    if any(visible[identity].knowledge_status != "ready" for identity in ids):
        raise HTTPException(status_code=409, detail="research_documents_not_ready")
    records = (
        await session.execute(
            select(CanonicalDocumentRecord, DocumentVersionRecord)
            .join(
                DocumentVersionRecord,
                DocumentVersionRecord.document_id == CanonicalDocumentRecord.id,
            )
            .where(
                CanonicalDocumentRecord.source_object_id.in_(ids),
                CanonicalDocumentRecord.customer_id == chat.customer_id,
                DocumentVersionRecord.superseded_at.is_(None),
            )
        )
    ).all()
    indexed = {document.source_object_id: (document, version) for document, version in records}
    if len(indexed) != len(ids):
        raise HTTPException(status_code=409, detail="research_document_version_missing")
    return [
        {
            "source_object_id": identity,
            "document_id": indexed[identity][0].id,
            "document_version_id": indexed[identity][1].id,
            "workspace_id": visible[identity].workspace_id,
        }
        for identity in ids
    ]


async def queue_workspace_research(
    session: AsyncSession,
    user: UserAccount,
    chat: WorkspaceChat,
    body: WorkspaceResearchRequest,
) -> Job:
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="research_question_required")
    manifest = await document_manifest(session, user, chat, body.source_object_ids)
    readable = await resolve_readable_workspace_ids(
        session,
        customer_id=chat.customer_id,
        user_id=user.id,
        workspace_id=chat.workspace_id,
    )
    now = utcnow()
    job = Job(
        id=f"job_{uuid4().hex[:16]}",
        customer_id=chat.customer_id,
        kind=JOB_KIND,
        status="pending",
        label=question[:120],
        created_at=now,
        updated_at=now,
        request={
            "chat_id": chat.id,
            "workspace_id": chat.workspace_id,
            "owner_user_id": user.id,
            "question": question,
            "module": chat.module,
            "entrypoint": body.entrypoint,
            "document_manifest": manifest,
            "readable_workspace_ids": readable,
        },
    )
    session.add(job)
    await session.flush()
    session.add(WorkspaceChatMessage(chat_id=chat.id, role="user", content=question, job_id=job.id))
    await session.commit()
    from app.services.jobs import enqueue_job

    enqueue_job(job.id)
    return job
