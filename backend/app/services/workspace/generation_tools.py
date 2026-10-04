"""Source-bound generation and durable research entry points."""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import DocumentVersionRecord, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact, WorkspaceOperation
from app.schemas.workspace import WorkspaceState
from app.services.workspace.service import artifact_out, new_id, require_expert, require_reference, require_source
from app.services.workspace.sources import citation, read_reference, source_version
from app.services.workspace.tool_arguments import ResearchArguments

async def require_shared_reference(session: AsyncSession, workspace: VoiceWorkspace, reference_id: str) -> None:
    ref = await require_reference(session, workspace, reference_id)
    version = await session.get(DocumentVersionRecord, ref.source_id) if ref.kind == "graph" else None
    if version is None or version.scope_key != "shared":
        raise HTTPException(status_code=409, detail="private_document_requires_workspace")
    await read_reference(session, workspace, reference_id)


def artifact_source_refs(content: dict) -> list[str]:
    return list({ref for block in content.get("blocks", []) for ref in block.get("source_refs", [])})


async def source_context(session: AsyncSession, workspace: VoiceWorkspace, source_refs: list[str], source_ids: list[str],
                         *, shared_only: bool = False) -> list[dict]:
    await require_source_scope(session, workspace, source_refs, source_ids, shared_only=shared_only)
    refs = list(source_refs)
    for source_id in source_ids:
        source = await require_source(session, workspace, source_id)
        if source.extraction_status != "ok" or not source.extracted_text:
            raise HTTPException(status_code=409, detail="workspace_source_not_readable")
        # Whole-document input is bounded, but never claims an invented PDF location.
        ref = await citation(session, workspace, kind="underlag", source_id=source.id, version=source_version(source),
                             anchor={"anchor_type": "text", "locator": "document", "exact_text": source.extracted_text[:20000], "rects": []},
                             snapshot={"title": source.filename, "excerpt": source.extracted_text[:20000],
                                       "truncated": len(source.extracted_text) > 20000, "total_chars": len(source.extracted_text)})
        refs.append(ref.id)
    result = []
    for reference_id in dict.fromkeys(refs):
        value = await read_reference(session, workspace, reference_id)
        if value["stale"]:
            raise HTTPException(status_code=409, detail="workspace_reference_stale")
        result.append({key: value[key] for key in ("reference_id", "number", "source_id", "source_version", "anchor", "snapshot")})
    return result


async def require_source_scope(session: AsyncSession, workspace: VoiceWorkspace, source_refs: list[str], source_ids: list[str],
                               *, shared_only: bool) -> None:
    if not shared_only:
        return
    if source_ids:
        await require_source(session, workspace, source_ids[0])
        raise HTTPException(status_code=409, detail="private_document_requires_workspace")
    for reference_id in dict.fromkeys(source_refs):
        await require_shared_reference(session, workspace, reference_id)


async def queue_generation(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount, operation: WorkspaceOperation,
                           *, kind: str, arguments: dict, artifact: WorkspaceArtifact | None = None) -> dict:
    from app.services.workspace_generation import queue_workspace_generation
    if artifact is None:
        artifact = WorkspaceArtifact(id=new_id(), workspace_id=workspace.id, kind=kind,
                                     title=arguments.get("title") or arguments.get("topic") or kind,
                                     status="queued", revision=0, content={})
        session.add(artifact)
        await session.flush()
    result = await queue_workspace_generation(session, workspace, user, artifact, operation=operation, arguments=arguments)
    return {**result, "artifact_id": artifact.id, "artifact": artifact_out(artifact)}


async def _start_research(session: AsyncSession, workspace: VoiceWorkspace, user: UserAccount,
                          operation: WorkspaceOperation, *, args: ResearchArguments) -> dict:
    if not args.confirmed:
        raise HTTPException(status_code=409, detail="research_confirmation_required")
    state = WorkspaceState.model_validate(operation.context_snapshot["state"])
    if state.expert_id is None:
        raise HTTPException(status_code=409, detail="workspace_expert_required")
    expert = await require_expert(session, workspace, state.expert_id)
    from app.services.expert_tools import resolve_expert_tools
    if "start_research" not in resolve_expert_tools(expert.tools):
        raise HTTPException(status_code=403, detail="workspace_expert_tool_not_allowed")
    from app.schemas.workspace_chat import WorkspaceResearchRequest
    from app.services.workspace.containers import require_container
    from app.services.workspace_research_start import prepare_workspace_research
    chat = await require_container(session, workspace, user)
    selected = args.source_object_ids
    if selected is None and state.documents:
        selected = [document.source_id for document in state.documents]
    job = await prepare_workspace_research(session, user, chat, WorkspaceResearchRequest(
        question=args.objective, source_object_ids=selected, entrypoint="tool",
    ))
    job.request = {**job.request, "voice_workspace_id": workspace.id,
                   "expert_id": state.expert_id, "operation_id": operation.id}
    return {"status": "queued", "run_id": None, "attempt_id": None, "job_id": job.id,
            "operation_id": operation.id, "progress_url": f"/jobs/{job.id}"}
