"""Small handlers behind the common workspace command boundary."""
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Job, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact, WorkspaceArtifactRevision, WorkspaceOperation, WorkspaceResearch
from app.schemas.workspace import WorkspaceState
from app.services.workspace.service import (
    add_source, artifact_out, new_id, publish_artifact_revision, require_artifact,
    require_source, require_workspace,
)
from app.services.workspace.sources import read_reference, search_research
from app.services.workspace.search import search_general, search_workspace
from app.services.workspace.research_links import job_bound_to_canvas, sync_research_links
from app.services.workspace.document_brief import document_conversation_brief
from app.services.workspace.generation_tools import artifact_source_refs, source_context, queue_generation, require_shared_reference, require_source_scope, _start_research
from app.services.workspace.tool_arguments import (
    SearchArguments, ReadArguments, IngestArguments, JobArguments, GenerationArguments,
    ReviseArguments, ExportArguments, ChartArguments, ResearchArguments, FindDocumentsArguments,
)
from app.services.document_navigation import exact_workspace_search, read_document_part
from app.services.document_find import (
    needs_embedding,
    normalize_find_mode,
    presentation_slice,
    run_find,
    suggested_title,
)
from app.services.document_find.id_map import document_ids_for_sources, source_ids_for_documents
from app.services.document_qa.tenants import require_tenant_catalogs
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider, require_embedding_vectors
from app.services.workspace_document_context import (
    created_document_read,
    ready_created_document,
)
from app.services.workspace_quote_focus import focus_passage
from app.services.workspace.source_ingest_retry import retry_failed_source
from app.services.workspace_turn_state import answered_workspace_context

@dataclass
class ToolContext:
    session: AsyncSession
    workspace: VoiceWorkspace
    user: UserAccount
    operation: WorkspaceOperation
    state: WorkspaceState
    language: str

async def context(context: ToolContext, arguments: dict) -> dict:
    return await answered_workspace_context(
        context.session,
        context.workspace,
        context.user,
        turn_context=context.operation.context_snapshot,
        arguments=arguments,
    )


async def find_documents(context: ToolContext, arguments: dict) -> dict:
    """OverGraph document find → complete source_ids for show_document_set."""
    session = context.session
    workspace = context.workspace
    state = context.state
    args = FindDocumentsArguments.model_validate(arguments)
    current_sources = _active_set_source_ids(state)
    current_docs = await document_ids_for_sources(session, current_sources)
    workspace_id = workspace.id
    customer_id = workspace.customer_id
    mode = normalize_find_mode(
        args.mode,
        has_current_set=bool(current_docs),
        query=args.query,
    )
    await session.commit()

    embed = needs_embedding(
        args.query, mode=mode, has_current_set=bool(current_docs),
    )
    dense_query = None
    if embed:
        context.operation.external_started = True
        dense_query = await _find_query_embedding(args.query)

    catalogs = require_tenant_catalogs()
    result = run_find(
        catalogs.open_for(customer_id),
        customer_id=customer_id,
        query=args.query,
        mode=mode,
        current_document_ids=current_docs,
        dense_query=dense_query,
        limit=args.limit,
    )
    await require_workspace(session, workspace_id, context.user)
    source_ids = await source_ids_for_documents(session, result.document_ids)
    shown, truncated = presentation_slice(source_ids)
    title = suggested_title(args.query, result)
    return {
        "status": "completed",
        "query": args.query,
        "mode": mode,
        "strategy": result.strategy,
        "completeness": result.completeness,
        "title": title,
        "document_ids": list(result.document_ids),
        "source_ids": source_ids,
        "document_count": len(source_ids),
        "presentation_source_ids": shown,
        "presentation_truncated": truncated,
        "notes": list(result.notes),
        "counters": {
            "embedding_calls": int(embed),
            "jev_calls": result.counters.jev_calls,
            "llm_calls": result.counters.llm_calls,
            "text_unit_reads": result.counters.text_unit_reads,
            "vector_searches": result.counters.vector_searches,
            "category_lookups": result.counters.category_lookups,
        },
        "db_ms": result.db_ms,
        "total_ms": result.total_ms,
    }


async def _find_query_embedding(query: str) -> tuple[float, ...]:
    embeddings = OpenAIEmbeddingProvider.from_settings()
    vectors = require_embedding_vectors(
        await embeddings.embed([query]), dimension=embeddings.dimension,
    )
    if len(vectors) != 1:
        raise RuntimeError("Embedding provider must return one query vector")
    return tuple(vectors[0])


def _active_set_source_ids(state: WorkspaceState) -> list[str]:
    active = state.active_document_set_id
    if not active:
        return []
    for row in state.document_sets or []:
        if row.id == active:
            return list(row.source_ids)
    return []


async def search(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    state = context.state
    args = SearchArguments.model_validate(arguments)
    scope = args.scope or state.knowledge_scope
    if scope != state.knowledge_scope:
        raise HTTPException(status_code=409, detail="selected_scope_conflict")
    if args.exact:
        if scope != "workspace":
            raise HTTPException(status_code=422, detail="exact_search_requires_workspace")
        result = await exact_workspace_search(
            session, workspace, args.query, limit=args.limit, source_id=args.source_id,
        )
        return {"status": "completed", "scope": scope, **result}
    created = await ready_created_document(session, workspace, args.source_id)
    if created is not None:
        if scope == "general":
            raise HTTPException(status_code=409, detail="private_document_requires_workspace")
        result = await exact_workspace_search(
            session, workspace, args.query, limit=args.limit, source_id=created.id,
        )
        return {"status": "completed", "scope": "workspace", **result}
    if scope in {"workspace", "general"}:
        context.operation.external_started = True
    if scope == "workspace":
        result = await search_workspace(session, workspace, args.query, args.limit, source_id=args.source_id)
    elif scope == "general":
        result = await search_general(session, workspace, args.query, args.limit)
    else:
        result = await search_research(session, workspace, args.query, args.limit, attempt_ids=state.research_attempt_ids)
    return {"status": "completed", "scope": scope, **result}


async def read(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    args = ReadArguments.model_validate(arguments)
    created = await ready_created_document(session, workspace, args.source_id)
    if created is not None and args.reference_id is None:
        if context.state.knowledge_scope == "general":
            raise HTTPException(status_code=409, detail="private_document_requires_workspace")
        return created_document_read(created, args.quote)
    if args.outline or args.section is not None or args.quote is not None or args.page is not None:
        if args.source_id is None:
            raise HTTPException(status_code=422, detail="source_or_reference_required")
        if context.state.knowledge_scope == "general":
            raise HTTPException(status_code=409, detail="private_document_requires_workspace")
        source = await require_source(session, workspace, args.source_id, member=False)
        source = await add_source(session, workspace, source.id)
        return await read_document_part(session, source, args)
    if args.reference_id:
        if context.state.knowledge_scope == "general":
            await require_shared_reference(session, workspace, args.reference_id)
        return {"status": "completed", **await read_reference(session, workspace, args.reference_id)}
    if args.source_id is None:
        raise HTTPException(status_code=422, detail="source_or_reference_required")
    source = await require_source(session, workspace, args.source_id, member=False)
    if context.state.knowledge_scope == "general":
        raise HTTPException(status_code=409, detail="private_document_requires_workspace")
    source = await add_source(session, workspace, source.id)
    refs = await source_context(session, workspace, [], [source.id])
    return {"status": "completed", **await read_reference(session, workspace, refs[0]["reference_id"]),
            "text": (source.extracted_text or "")[:20000], "ingest_status": source.knowledge_status}


async def ingest(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    operation = context.operation
    args = IngestArguments.model_validate(arguments)
    if (args.source_id is None) == (args.url is None):
        raise HTTPException(status_code=422, detail="source_id_or_url_required")
    if args.url:
        from app.services.workspace.ingest import ingest_url
        return await ingest_url(session, workspace, operation, url=args.url)
    source = await add_source(session, workspace, args.source_id)
    return await retry_failed_source(session, workspace, source)


async def job(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    user = context.user
    args = JobArguments.model_validate(arguments)
    await sync_research_links(session, workspace)
    if args.attempt_id:
        if await session.get(WorkspaceResearch, (workspace.id, args.attempt_id)) is None:
            raise HTTPException(status_code=404, detail="workspace_research_not_found")
        from app.database.models import ExecutionAttempt
        attempt = await session.get(ExecutionAttempt, args.attempt_id)
        return {"status": "completed", "attempt_id": attempt.id, "research_status": attempt.status}
    job = await session.get(Job, args.job_id) if args.job_id else None
    if job is None or job.customer_id != workspace.customer_id:
        raise HTTPException(status_code=404, detail="workspace_job_not_found")
    request = job.request or {}
    if request.get("voice_workspace_id") is not None:
        if not job_bound_to_canvas(job, workspace):
            raise HTTPException(status_code=404, detail="workspace_job_not_found")
    else:
        source = await require_source(session, workspace, str(request.get("object_id") or ""))
        if request.get("workspace_id") != source.workspace_id:
            raise HTTPException(status_code=404, detail="workspace_job_not_found")
    if request.get("owner_user_id") and request["owner_user_id"] != user.id:
        raise HTTPException(status_code=404, detail="workspace_job_not_found")
    return {"status": "completed", "job_id": job.id, "job_status": job.status, "result": job.result, "error": job.error}


async def generate(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    user = context.user
    operation = context.operation
    tool_name = context.operation.tool_name
    args = GenerationArguments.model_validate(arguments)
    kind = {"create_document": "document", "compare_sources": "comparison", "get_relations": "relations"}[tool_name]
    values = args.model_dump()
    values["language"] = context.language
    values["source_context"] = await source_context(session, workspace, args.source_refs, args.source_ids,
        shared_only=context.state.knowledge_scope == "general")
    if kind == "document":
        values["conversation_brief"] = await document_conversation_brief(session, context.state.expert_id)
    if kind != "document" and not values["source_context"]:
        raise HTTPException(status_code=422, detail="cited_sources_required")
    return await queue_generation(session, workspace, user, operation, kind=kind, arguments=values)


async def revise(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    user = context.user
    operation = context.operation
    args = ReviseArguments.model_validate(arguments)
    selection = context.state.selection
    if selection and selection.artifact_id:
        if args.artifact_id != selection.artifact_id or args.expected_revision != selection.artifact_revision:
            raise HTTPException(status_code=409, detail="selected_artifact_conflict")
        if selection.block_id:
            if args.block_id and args.block_id != selection.block_id:
                raise HTTPException(status_code=409, detail="selected_block_conflict")
            args.block_id = selection.block_id
    artifact = await require_artifact(session, workspace, args.artifact_id)
    if artifact.kind != "document" or artifact.revision != args.expected_revision:
        raise HTTPException(status_code=409, detail="artifact_revision_conflict")
    if args.block_id and not any(block.get("id") == args.block_id for block in artifact.content.get("blocks", [])):
        raise HTTPException(status_code=404, detail="artifact_block_not_found")
    refs = artifact_source_refs(artifact.content) + artifact_source_refs(args.content or {})
    await require_source_scope(session, workspace, refs, [], shared_only=context.state.knowledge_scope == "general")
    if args.content is not None:
        if args.block_id:
            from app.services.workspace_generation import _validate_selected_revision
            try:
                _validate_selected_revision(args.content, {"base_content": artifact.content, "block_id": args.block_id})
            except (ValueError, KeyError) as exc:
                raise HTTPException(status_code=422, detail="unselected_document_block_changed") from exc
        await publish_artifact_revision(session, artifact, expected_revision=args.expected_revision, content=args.content, title=args.title)
        return {"status": "completed", "artifact_id": artifact.id, "artifact": artifact_out(artifact)}
    if not args.instructions.strip():
        raise HTTPException(status_code=422, detail="revision_instructions_required")
    values = args.model_dump()
    values["language"] = context.language
    values["source_context"] = await source_context(session, workspace, refs, [],
        shared_only=context.state.knowledge_scope == "general")
    values["base_content"] = artifact.content
    return await queue_generation(session, workspace, user, operation, kind="document", artifact=artifact, arguments=values)


async def export(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    args = ExportArguments.model_validate(arguments)
    artifact = await require_artifact(session, workspace, args.artifact_id)
    if artifact.kind != "document" or await session.get(WorkspaceArtifactRevision, (artifact.id, args.revision)) is None:
        raise HTTPException(status_code=404, detail="artifact_revision_not_found")
    return {"status": "completed", "artifact_id": artifact.id, "revision": args.revision, "format": args.format,
            "download_url": f"/workspaces/{workspace.id}/artifacts/{artifact.id}/exports/{args.format}?revision={args.revision}"}


async def chart(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    args = ChartArguments.model_validate(arguments)
    await source_context(session, workspace, args.source_refs, [], shared_only=context.state.knowledge_scope == "general")
    artifact = WorkspaceArtifact(id=new_id(), workspace_id=workspace.id, kind="chart", title=args.title,
                                 revision=0, status="queued", content={})
    session.add(artifact)
    await session.flush()
    await publish_artifact_revision(session, artifact, expected_revision=0, content=args.model_dump())
    return {"status": "completed", "artifact_id": artifact.id, "artifact": artifact_out(artifact)}


async def research(context: ToolContext, arguments: dict) -> dict:
    session = context.session
    workspace = context.workspace
    user = context.user
    operation = context.operation
    return await _start_research(session, workspace, user, operation, args=ResearchArguments.model_validate(arguments))

HANDLERS = {
    "get_workspace_context": context, "search_knowledge": search, "find_documents": find_documents,
    "read_source": read, "ingest_source": ingest, "get_job_status": job, "create_document": generate,
    "compare_sources": generate, "get_relations": generate, "revise_document": revise,
    "export_document": export, "render_chart": chart, "start_research": research,
    "focus_passage": focus_passage,
}
