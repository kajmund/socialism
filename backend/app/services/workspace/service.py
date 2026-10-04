"""VoiceWorkspace authorization, compare-and-swap state and artifact publication."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExecutionAttempt, Persona, StoredObject, UserAccount
from app.database.workspace_models import (
    VoiceWorkspace, WorkspaceArtifact, WorkspaceArtifactRevision, WorkspaceExpertThread,
    WorkspaceOperation, WorkspaceReference, WorkspaceResearch, WorkspaceSource,
)
from app.modules.registry import MODULE_REGISTRY
from app.schemas.workspace import WorkspaceState
from app.services.stored_objects import serialize_underlag
from app.services.workspace_chats import require_chat_file
from app.services.workspace.containers import WorkspaceContainer, creation_chat, require_container
from app.services.workspaces import require_workspace_customer
from app.services.workspace.research_links import sync_research_links as sync_research_links


def new_id() -> str:
    return str(uuid4())


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


async def require_workspace(session: AsyncSession, workspace_id: str, user: UserAccount) -> VoiceWorkspace:
    row = await session.get(VoiceWorkspace, workspace_id)
    if row is None or row.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    await require_container(session, row, user)
    return row


async def require_source(session: AsyncSession, workspace: VoiceWorkspace, source_id: str, *, member: bool = True) -> StoredObject:
    user = await session.get(UserAccount, workspace.owner_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    chat = await require_container(session, workspace, user)
    source = await require_chat_file(session, user, chat, source_id)
    if source.module != workspace.module:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    if member and await session.get(WorkspaceSource, (workspace.id, source_id)) is None:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    return source


async def require_expert(session: AsyncSession, workspace: VoiceWorkspace, expert_id: str) -> Persona:
    expert = await session.get(Persona, expert_id)
    if expert is None or expert.customer_id != workspace.customer_id or expert.kind != "expert":
        raise HTTPException(status_code=404, detail="workspace_expert_not_found")
    return expert


async def create_workspace(session: AsyncSession, user: UserAccount, *, title: str, module: str,
                           idempotency_key: str | None = None, language: str = "sv",
                           container: WorkspaceContainer | None = None) -> VoiceWorkspace:
    if module not in MODULE_REGISTRY:
        raise HTTPException(status_code=422, detail="unknown_module")
    container = container or WorkspaceContainer()
    customer_id = await require_workspace_customer(session, user, container.customer_id)
    creation_key = idempotency_key or new_id()
    payload_hash = fingerprint({"title": title, "module": module, "language": language,
        "workspace_id": container.workspace_id, "chat_id": container.chat_id, "customer_id": customer_id})
    existing = await session.scalar(select(VoiceWorkspace).where(VoiceWorkspace.owner_user_id == user.id,
                                                                VoiceWorkspace.creation_key == creation_key))
    if existing is not None:
        await require_container(session, existing, user)
        if existing.creation_payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="workspace_idempotency_conflict")
        return existing
    chat = await creation_chat(session, user, container, title=title, module=module, creation_key=creation_key)
    linked = await session.scalar(select(VoiceWorkspace).where(VoiceWorkspace.chat_id == chat.id))
    if linked is not None:
        return await require_workspace(session, linked.id, user)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    await session.execute(insert(VoiceWorkspace).values(id=new_id(), customer_id=customer_id,
        workspace_id=chat.workspace_id, chat_id=chat.id,
        owner_user_id=user.id, creation_key=creation_key, creation_payload_hash=payload_hash,
        title=title.strip(), module=module, state=WorkspaceState(language=language).model_dump(), revision=0,
        next_reference_number=1).on_conflict_do_nothing())
    workspace = await session.scalar(select(VoiceWorkspace).where(VoiceWorkspace.owner_user_id == user.id,
        or_(VoiceWorkspace.creation_key == creation_key, VoiceWorkspace.chat_id == chat.id)))
    if workspace.creation_key != creation_key:
        return await require_workspace(session, workspace.id, user)
    if workspace.customer_id != customer_id or workspace.creation_payload_hash != payload_hash:
        raise HTTPException(status_code=409, detail="workspace_idempotency_conflict")
    return workspace


async def require_artifact(session: AsyncSession, workspace: VoiceWorkspace, artifact_id: str) -> WorkspaceArtifact:
    artifact = await session.get(WorkspaceArtifact, artifact_id)
    if artifact is None or artifact.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="workspace_artifact_not_found")
    return artifact


async def require_reference(session: AsyncSession, workspace: VoiceWorkspace, reference_id: str) -> WorkspaceReference:
    reference = await session.get(WorkspaceReference, reference_id)
    if reference is None or reference.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="workspace_reference_not_found")
    return reference


async def validate_state(session: AsyncSession, workspace: VoiceWorkspace, state: WorkspaceState) -> None:
    if state.expert_id:
        await require_expert(session, workspace, state.expert_id)
        if await session.get(WorkspaceExpertThread, (workspace.id, state.expert_id)) is None:
            session.add(WorkspaceExpertThread(workspace_id=workspace.id, expert_id=state.expert_id))
    for source_id in {tab.source_id for tab in state.documents} | set(state.split_source_ids):
        await require_source(session, workspace, source_id)
    for tab in state.documents:
        if tab.reference_id:
            reference = await require_reference(session, workspace, tab.reference_id)
            if reference.kind != "underlag" or reference.source_id != tab.source_id:
                raise HTTPException(status_code=409, detail="document_anchor_source_conflict")
    for attempt_id in state.research_attempt_ids:
        if await session.get(WorkspaceResearch, (workspace.id, attempt_id)) is None:
            raise HTTPException(status_code=404, detail="workspace_research_not_found")
    if state.active_artifact_id:
        await require_artifact(session, workspace, state.active_artifact_id)
    await _validate_selection(session, workspace, state)


async def _validate_selection(session: AsyncSession, workspace: VoiceWorkspace, state: WorkspaceState) -> None:
    selection = state.selection
    if selection is None:
        return
    if selection.reference_id:
        await _validate_reference_selection(session, workspace, state)
    if selection.source_id:
        source = await require_source(session, workspace, selection.source_id)
        if selection.anchor is None:
            raise HTTPException(status_code=422, detail="selection_anchor_required")
        from app.services.workspace.sources import citation, source_version
        from app.services.document_knowledge import _normalized
        exact_text = selection.anchor.exact_text or ""
        if not exact_text or _normalized(exact_text) not in _normalized(source.extracted_text or ""):
            raise HTTPException(status_code=409, detail="selection_anchor_stale")
        reference = await citation(session, workspace, kind="underlag", source_id=source.id,
            version=source_version(source), anchor=selection.anchor.model_dump(),
            snapshot={"title": source.filename, "excerpt": exact_text})
        selection.reference_id = reference.id
    if selection.artifact_id:
        artifact = await require_artifact(session, workspace, selection.artifact_id)
        content = artifact.content
        if selection.artifact_revision is not None:
            revision = await session.get(WorkspaceArtifactRevision, (artifact.id, selection.artifact_revision))
            if revision is None:
                raise HTTPException(status_code=404, detail="artifact_revision_not_found")
            content = revision.content
        else:
            selection.artifact_revision = artifact.revision
        for key, field in (("blocks", selection.block_id), ("nodes", selection.node_id), ("edges", selection.edge_id)):
            if field and not any(item.get("id") == field for item in content.get(key, [])):
                raise HTTPException(status_code=404, detail="workspace_selection_not_found")
    elif selection.block_id or selection.node_id or selection.edge_id or selection.artifact_revision:
        raise HTTPException(status_code=422, detail="selection_requires_artifact")


async def _validate_reference_selection(session: AsyncSession, workspace: VoiceWorkspace, state: WorkspaceState) -> None:
    from app.services.document_knowledge import _normalized
    from app.services.workspace.sources import citation, read_reference
    selection = state.selection
    reference = await require_reference(session, workspace, selection.reference_id)
    current = await read_reference(session, workspace, reference.id)
    if current["stale"]:
        raise HTTPException(status_code=409, detail="workspace_reference_stale")
    if selection.anchor is None:
        return
    anchor = selection.anchor.model_dump()
    quote = anchor.get("exact_text") or ""
    if (not quote or _normalized(quote) not in _normalized(reference.snapshot.get("excerpt") or "")
            or any(anchor.get(field) != reference.anchor.get(field) for field in ("page_number", "locator"))):
        raise HTTPException(status_code=409, detail="selection_anchor_stale")
    selected = await citation(session, workspace, kind=reference.kind, source_id=reference.source_id,
        version=reference.source_version, anchor=anchor,
        snapshot={**reference.snapshot, "excerpt": quote, "parent_reference_id": reference.id})
    selection.reference_id = selected.id


async def patch_workspace(session: AsyncSession, workspace: VoiceWorkspace, *, expected_revision: int,
                          state: WorkspaceState | None = None, title: str | None = None) -> VoiceWorkspace:
    if state is not None:
        await validate_state(session, workspace, state)
    values: dict = {"revision": expected_revision + 1, "updated_at": datetime.now(UTC)}
    if state is not None:
        values["state"] = state.model_dump()
    if title is not None:
        values["title"] = title.strip()
    result = await session.execute(update(VoiceWorkspace).where(VoiceWorkspace.id == workspace.id, VoiceWorkspace.revision == expected_revision).values(**values))
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="workspace_revision_conflict")
    await session.refresh(workspace)
    return workspace


async def add_source(session: AsyncSession, workspace: VoiceWorkspace, source_id: str, *, source_url: str | None = None) -> StoredObject:
    source = await require_source(session, workspace, source_id, member=False)
    if await session.get(WorkspaceSource, (workspace.id, source_id)) is None:
        session.add(WorkspaceSource(workspace_id=workspace.id, source_id=source_id, source_url=source_url))
        await session.flush()
    return source


async def accept_operation(session: AsyncSession, workspace: VoiceWorkspace, *, tool_name: str,
                           arguments: dict, idempotency_key: str, expected_revision: int | None = None,
                           context_snapshot: dict | None = None) -> tuple[WorkspaceOperation, bool]:
    digest = fingerprint({"tool": tool_name, "arguments": arguments, "expected_revision": expected_revision})
    query = select(WorkspaceOperation).where(WorkspaceOperation.workspace_id == workspace.id,
                                           WorkspaceOperation.idempotency_key == idempotency_key)
    existing = (await session.execute(query)).scalar_one_or_none()
    if existing is not None:
        if existing.payload_hash != digest:
            raise HTTPException(status_code=409, detail="workspace_idempotency_conflict")
        return existing, False
    if context_snapshot is None and expected_revision is not None and workspace.revision != expected_revision:
        raise HTTPException(status_code=409, detail="workspace_revision_conflict")
    operation_id = new_id()
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    result = await session.execute(insert(WorkspaceOperation).values(
        id=operation_id, workspace_id=workspace.id, idempotency_key=idempotency_key,
        payload_hash=digest, tool_name=tool_name, status="accepted",
        context_snapshot=context_snapshot or {"revision": workspace.revision, "state": dict(workspace.state)},
        result={}).on_conflict_do_nothing(index_elements=["workspace_id", "idempotency_key"]))
    operation = (await session.execute(query)).scalar_one()
    if operation.payload_hash != digest:
        raise HTTPException(status_code=409, detail="workspace_idempotency_conflict")
    return operation, result.rowcount == 1




async def publish_artifact_revision(session: AsyncSession, artifact: WorkspaceArtifact, *, expected_revision: int,
                                    content: dict, title: str | None = None) -> WorkspaceArtifact:
    from app.services.workspace.artifact_validation import validate_artifact_content
    await validate_artifact_content(session, artifact, content)
    next_revision = expected_revision + 1
    result = await session.execute(update(WorkspaceArtifact).where(WorkspaceArtifact.id == artifact.id,
                                                                 WorkspaceArtifact.revision == expected_revision).values(
        revision=next_revision, content=content, title=title or artifact.title, status="ready", error=None, updated_at=datetime.now(UTC)))
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="artifact_revision_conflict")
    session.add(WorkspaceArtifactRevision(artifact_id=artifact.id, revision=next_revision,
                                         title=title or artifact.title, content=content))
    await session.flush()
    await session.refresh(artifact)
    return artifact


def artifact_out(artifact: WorkspaceArtifact) -> dict:
    return {"id": artifact.id, "workspace_id": artifact.workspace_id, "kind": artifact.kind, "title": artifact.title,
            "status": artifact.status, "revision": artifact.revision, "content": artifact.content,
            "job_id": artifact.job_id, "error": artifact.error}


async def workspace_out(session: AsyncSession, workspace: VoiceWorkspace) -> dict:
    queued_research = await sync_research_links(session, workspace)
    sources = list((await session.execute(select(StoredObject).join(WorkspaceSource, WorkspaceSource.source_id == StoredObject.id)
                                         .where(WorkspaceSource.workspace_id == workspace.id, StoredObject.customer_id == workspace.customer_id))).scalars())
    sources = [await require_source(session, workspace, row.id) for row in sources]
    artifacts = list((await session.execute(select(WorkspaceArtifact).where(WorkspaceArtifact.workspace_id == workspace.id)
                                           .order_by(WorkspaceArtifact.created_at))).scalars())
    refs = list((await session.execute(select(WorkspaceReference).where(WorkspaceReference.workspace_id == workspace.id)
                                      .order_by(WorkspaceReference.number))).scalars())
    attempts = list((await session.scalars(select(ExecutionAttempt).join(WorkspaceResearch, WorkspaceResearch.attempt_id == ExecutionAttempt.id)
        .where(WorkspaceResearch.workspace_id == workspace.id).order_by(ExecutionAttempt.created_at))).all())
    return {"id": workspace.id, "workspace_id": workspace.workspace_id, "chat_id": workspace.chat_id,
            "customer_id": workspace.customer_id, "title": workspace.title, "module": workspace.module, "revision": workspace.revision,
            "state": workspace.state, "sources": [serialize_underlag(row, include_text=False) for row in sources],
            "artifacts": [artifact_out(row) for row in artifacts],
            "research": queued_research + [{"job_id": None, "attempt_id": row.id, "run_id": row.run_id, "status": row.status,
                          "progress_url": f"/execution/attempts/{row.id}/progress-events"} for row in attempts
                          if row.id not in {item["attempt_id"] for item in queued_research}],
            "references": [await _reference_summary(session, workspace, ref) for ref in refs]}


async def _reference_summary(session: AsyncSession, workspace: VoiceWorkspace, ref: WorkspaceReference) -> dict:
    from app.services.workspace.sources import read_reference, reference_out
    try:
        return await read_reference(session, workspace, ref.id)
    except HTTPException as exc:
        if exc.status_code not in {404, 409}:
            raise
        return {**reference_out(ref, stale=True), "unavailable": True}
