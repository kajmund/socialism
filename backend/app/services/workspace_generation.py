"""Persisted, source-bound workspace generation using the existing job runner."""

from __future__ import annotations

import json
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Job, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact, WorkspaceOperation
from app.llm import complete_structured_retry
from app.serializers import utcnow
from app.services.prompt_store import render_prompt, require_active_prompts

WORKSPACE_GENERATION_JOB_KIND = "workspace_generation"


class WorkspaceGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice_workspace_id: str
    workspace_id: str
    chat_id: str
    artifact_id: str
    operation_id: str
    owner_user_id: str
    expected_revision: int = Field(ge=0)
    language: Literal["sv", "en", "nb"] = "sv"
    arguments: dict


class DocumentBlock(BaseModel):
    id: str
    type: Literal["heading", "paragraph"]
    text: str
    source_refs: list[str]


class GeneratedDocument(BaseModel):
    blocks: list[DocumentBlock] = Field(min_length=1, max_length=500)


class ComparisonCell(BaseModel):
    text: str | None
    source_refs: list[str]


class ComparisonRow(BaseModel):
    id: str
    label: str
    cells: list[ComparisonCell]


class GeneratedComparison(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=30)
    rows: list[ComparisonRow] = Field(min_length=1, max_length=200)


class RelationNode(BaseModel):
    id: str
    label: str
    kind: Literal["event", "condition", "effect", "interpretation"]
    source_refs: list[str]


class RelationEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    source_refs: list[str]
    interpretation: bool


class GeneratedRelations(BaseModel):
    nodes: list[RelationNode] = Field(min_length=1, max_length=100)
    edges: list[RelationEdge] = Field(max_length=200)


async def queue_workspace_generation(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    user: UserAccount,
    artifact: WorkspaceArtifact,
    *,
    operation: WorkspaceOperation,
    arguments: dict,
) -> dict:
    """Create job in the caller's transaction; scheduling happens after commit."""
    if workspace.owner_user_id != user.id or artifact.workspace_id != workspace.id:
        raise ValueError("VoiceWorkspace generation ownership mismatch")
    payload = WorkspaceGenerationRequest(
        voice_workspace_id=workspace.id,
        workspace_id=workspace.workspace_id,
        chat_id=workspace.chat_id,
        artifact_id=artifact.id,
        operation_id=operation.id,
        owner_user_id=user.id,
        expected_revision=artifact.revision,
        language=arguments.get("language", "sv"),
        arguments=arguments,
    )
    job = Job(
        id=f"job_{secrets.token_hex(8)}",
        customer_id=workspace.customer_id,
        kind=WORKSPACE_GENERATION_JOB_KIND,
        status="pending",
        label=artifact.title,
        request=payload.model_dump(mode="json"),
        result=None,
        error=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(job)
    await session.flush()
    artifact.job_id = job.id
    artifact.status = "queued"
    artifact.error = None
    operation.job_id = job.id
    operation.status = "queued"
    return {"artifact_id": artifact.id, "job_id": job.id, "status": "queued"}


async def validate_generation_job(session: AsyncSession, payload: WorkspaceGenerationRequest) -> VoiceWorkspace:
    workspace = await session.get(VoiceWorkspace, payload.voice_workspace_id)
    artifact = await session.get(WorkspaceArtifact, payload.artifact_id)
    operation = await session.get(WorkspaceOperation, payload.operation_id)
    user = await session.get(UserAccount, payload.owner_user_id)
    if (
        workspace is None or artifact is None or operation is None or user is None
        or workspace.owner_user_id != user.id
        or artifact.workspace_id != workspace.id
        or operation.workspace_id != workspace.id
        or payload.workspace_id != workspace.workspace_id
        or payload.chat_id != workspace.chat_id
    ):
        raise ValueError("VoiceWorkspace generation not found")
    from app.services.workspace.service import require_workspace
    await require_workspace(session, workspace.id, user)
    await _validate_generation_sources(session, workspace, payload.arguments.get("source_context", []))
    return workspace


async def _validate_generation_sources(session: AsyncSession, workspace: VoiceWorkspace, sources: list[dict]) -> None:
    from app.services.workspace.sources import read_reference
    for snapshot in sources:
        current = await read_reference(session, workspace, snapshot["reference_id"])
        if current["stale"] or any(current[key] != snapshot[key] for key in (
                "reference_id", "number", "source_id", "source_version", "anchor", "snapshot")):
            raise ValueError("VoiceWorkspace generation source has changed")


def _validate_relations(content: dict, check_refs) -> list[str]:
    ids = [node["id"] for node in content["nodes"]]
    for node in content["nodes"]:
        check_refs(node["source_refs"])
        if node["kind"] != "interpretation" and not node["source_refs"]:
            raise ValueError("Relation facts require evidence")
    edge_ids = [edge["id"] for edge in content["edges"]]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("Duplicate relation edge IDs")
    for edge in content["edges"]:
        check_refs(edge["source_refs"])
        if edge["source"] not in ids or edge["target"] not in ids:
            raise ValueError("Relation edge has a missing endpoint")
        if not edge["interpretation"] and not edge["source_refs"]:
            raise ValueError("Relation edges require evidence or an interpretation label")
    return ids


def _validate_generated_content(kind: str, content: dict, source_context: list[dict]) -> None:
    allowed = {row["reference_id"] for row in source_context}

    def check_refs(refs: list[str]) -> None:
        if not set(refs).issubset(allowed):
            raise ValueError("Generated artifact contains an unknown source reference")

    if kind == "document":
        ids = [block["id"] for block in content["blocks"]]
        for block in content["blocks"]:
            check_refs(block["source_refs"])
    elif kind == "comparison":
        ids = [row["id"] for row in content["rows"]]
        for row in content["rows"]:
            if len(row["cells"]) != len(content["columns"]):
                raise ValueError("Comparison cells do not match columns")
            for cell in row["cells"]:
                check_refs(cell["source_refs"])
                if cell["text"] is not None and not cell["source_refs"]:
                    raise ValueError("Comparison claims require evidence")
    else:
        ids = _validate_relations(content, check_refs)
    if len(ids) != len(set(ids)) or any(not value.strip() for value in ids):
        raise ValueError("Generated artifact IDs must be nonempty and unique")


def _validate_selected_revision(content: dict, arguments: dict) -> None:
    base = arguments.get("base_content")
    block_id = arguments.get("block_id")
    if not base or not block_id:
        return
    old_blocks = base["blocks"]
    new_blocks = content["blocks"]
    if [block["id"] for block in old_blocks] != [block["id"] for block in new_blocks]:
        raise ValueError("Selected-block revision changed document structure")
    for old, new in zip(old_blocks, new_blocks, strict=True):
        if old["id"] != block_id and old != new:
            raise ValueError("Selected-block revision changed an unselected block")


async def run_workspace_generation_job(
    factory: async_sessionmaker[AsyncSession], *, job_id: str,
) -> dict:
    from app.services.workspace.service import publish_artifact_revision

    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError("VoiceWorkspace generation job not found")
        payload = WorkspaceGenerationRequest.model_validate(job.request)
        workspace = await validate_generation_job(session, payload)
        artifact = await session.get(WorkspaceArtifact, payload.artifact_id)
        assert artifact is not None
        kind = artifact.kind
        title = artifact.title
        if kind not in {"document", "comparison", "relations"}:
            raise ValueError(f"Unsupported workspace generation kind: {kind}")
        prompts = await require_active_prompts(
            session, customer_id=workspace.customer_id, module=workspace.module,
            language=payload.language,
        )
        source_context = payload.arguments.get("source_context", [])
        request = {key: value for key, value in payload.arguments.items() if key != "source_context"}
        messages = [
            {"role": "system", "content": render_prompt(prompts, f"workspace.generate.{kind}.system")},
            {"role": "user", "content": render_prompt(
                prompts, "workspace.generate.user", title=title,
                request_json=json.dumps(request, ensure_ascii=False),
                source_context_json=json.dumps(source_context, ensure_ascii=False),
            )},
        ]

    model = {"document": GeneratedDocument, "comparison": GeneratedComparison, "relations": GeneratedRelations}[kind]
    generated = await complete_structured_retry(messages, model, prompt_key=f"workspace.generate.{kind}.system")
    content = generated.model_dump(mode="json")
    _validate_generated_content(kind, content, source_context)
    if kind == "document":
        _validate_selected_revision(content, payload.arguments)

    async with factory() as session:
        await validate_generation_job(session, payload)
        artifact = await session.get(WorkspaceArtifact, payload.artifact_id)
        operation = await session.get(WorkspaceOperation, payload.operation_id)
        assert artifact is not None and operation is not None
        if artifact.job_id != job_id:
            raise ValueError("VoiceWorkspace generation has been superseded")
        await publish_artifact_revision(
            session, artifact, expected_revision=payload.expected_revision,
            content=content, title=title,
        )
        artifact.status = "ready"
        artifact.error = None
        operation.status = "completed"
        operation.result = {
            "artifact_id": artifact.id, "job_id": job_id, "status": "ready",
            "revision": artifact.revision,
        }
        await session.commit()
        return operation.result


async def apply_workspace_job_status(session: AsyncSession, job: Job, status: str, *, error: str | None = None) -> None:
    if job.kind != WORKSPACE_GENERATION_JOB_KIND:
        return
    payload = WorkspaceGenerationRequest.model_validate(job.request)
    artifact = await session.get(WorkspaceArtifact, payload.artifact_id)
    operation = await session.get(WorkspaceOperation, payload.operation_id)
    if artifact is not None and artifact.job_id == job.id and (
        status != "failed" or artifact.revision == payload.expected_revision
    ):
        artifact.status = {"running": "running", "failed": "failed", "succeeded": "ready"}[status]
        artifact.error = error
    if operation is not None and operation.job_id == job.id and status == "failed":
        operation.status = "failed"
        operation.result = {"status": "failed", "job_id": job.id, "artifact_id": payload.artifact_id, "error": error}


async def fail_interrupted_workspace_jobs(session: AsyncSession, message: str) -> None:
    rows = await session.execute(select(Job).where(Job.kind == WORKSPACE_GENERATION_JOB_KIND, Job.status.in_(("pending", "running"))))
    for job in rows.scalars():
        await apply_workspace_job_status(session, job, "failed", error=message)
