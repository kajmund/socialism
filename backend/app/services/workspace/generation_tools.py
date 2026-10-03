"""Source-bound generation and durable research entry points."""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import UserAccount
from app.database.workspace_models import Workspace, WorkspaceArtifact, WorkspaceOperation, WorkspaceResearch
from app.schemas.workspace import WorkspaceState
from app.services.workspace.service import artifact_out, new_id, require_expert, require_source
from app.services.workspace.sources import citation, read_reference, source_version
from app.services.workspace.tool_arguments import ResearchArguments

async def source_context(session: AsyncSession, workspace: Workspace, source_refs: list[str], source_ids: list[str]) -> list[dict]:
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


async def queue_generation(session: AsyncSession, workspace: Workspace, user: UserAccount, operation: WorkspaceOperation,
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


async def _start_research(session: AsyncSession, workspace: Workspace, user: UserAccount,
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
    from app.services.execution.service import create_attempt, create_run
    from app.services.research_worker import accept_attempt_research
    run = await create_run(session, customer_id=workspace.customer_id, module=workspace.module, title=args.objective[:255],
        context={"workspace_id": workspace.id, "owner_user_id": user.id, "expert_id": state.expert_id})
    attempt = await create_attempt(session, run_id=run.id, attempt_type="workspace_research",
        input_snapshot={"objective": args.objective}, configuration_snapshot={"expert_id": state.expert_id})
    session.add(WorkspaceResearch(workspace_id=workspace.id, attempt_id=attempt.id))
    result = {"status": "queued", "run_id": run.id, "attempt_id": attempt.id, "job_id": None,
              "operation_id": operation.id, "progress_url": f"/execution/attempts/{attempt.id}/progress-events"}
    operation.status, operation.result = "queued", result
    # Existing durable research claims own this lifecycle, including their recovery.
    await accept_attempt_research(session, attempt_id=attempt.id, research_objective=args.objective,
                                 research_context={"workspace_id": workspace.id, "owner_user_id": user.id}, research_plan=None)
    return result
