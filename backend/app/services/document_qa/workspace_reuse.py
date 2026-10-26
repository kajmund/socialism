"""Exact reuse of a finished workspace answer. Not a semantic cache."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job
from app.database.workspaces import WorkspaceChatMessage
from app.services.document_qa.access import Viewer
from app.services.document_qa.from_workspace import (
    WorkspaceQuestion,
    workspace_analysis_contract,
    workspace_question,
)
from app.services.document_qa.outbox import require_owned_ids
from app.services.document_qa.owner_qa_retrieve import exact_reuse as exact_reuse_owner
from app.services.overgraph.owner_registry import tenant_owner_client
from app.services.document_qa.types import ExactHit, LoadedCite
from app.services.graph_v2.errors import PermanentGraphError
from app.services.overgraph.owner import OwnerClient


async def try_reuse_workspace_answer(session: AsyncSession, job_id: str) -> dict | None:
    job = await session.get(Job, job_id)
    saved = _finished_answer(job)
    if saved is not None or job is None:
        return saved
    asked = workspace_question(job)
    if asked is None or job.result:
        return None
    try:
        await require_owned_ids(
            session, asked.customer_id, asked.document_id, asked.document_version_id,
        )
    except PermanentGraphError:
        await session.rollback()
        return None
    chat_id = str(job.request.get("chat_id") or "")
    await session.rollback()
    hit = await exact_hit_for_question_owner(
        tenant_owner_client(asked.customer_id), asked,
    )
    if hit is None or not chat_id:
        return None
    result = result_from_hit(hit, asked.source_object_id)
    await _deliver(session, job_id, chat_id, result)
    return result


def _finished_answer(job: Job | None) -> dict | None:
    if job is None or job.kind != "workspace_research":
        return None
    saved = dict(job.result or {})
    if saved.get("answer"):
        return saved
    return None


async def exact_hit_for_question_owner(
    client: OwnerClient, asked: WorkspaceQuestion,
) -> ExactHit | None:
    return await exact_reuse_owner(
        client,
        Viewer(
            customer_id=asked.customer_id,
            workspace_id=asked.workspace_id,
            readable_document_ids=frozenset({asked.document_id}),
            readable_version_ids=frozenset({asked.document_version_id}),
        ),
        question_text=asked.question,
        document_id=asked.document_id,
        document_version_id=asked.document_version_id,
        contract=workspace_analysis_contract(),
    )


def result_from_hit(hit: ExactHit, source_object_id: str) -> dict[str, object]:
    cites = [cite for post in hit.answer.posts for cite in post.sources]
    return {
        "answer": hit.answer.text,
        "reuse": "exact",
        "citations": [
            _citation(index, cite, source_object_id) for index, cite in enumerate(cites, 1)
        ],
    }


def _citation(index: int, cite: LoadedCite, source_object_id: str) -> dict[str, object]:
    return {
        "label": f"E{index}",
        "source_object_id": source_object_id or None,
        "document_version_id": cite.document_version_id,
        "text_unit_id": cite.text_unit_id,
        "excerpt": cite.excerpt,
    }


async def _deliver(
    session: AsyncSession, job_id: str, chat_id: str, result: dict[str, object],
) -> None:
    existing = await session.get(Job, job_id)
    existing.result = {**(existing.result or {}), **result}
    session.add(WorkspaceChatMessage(
        chat_id=chat_id, role="assistant", content=str(result["answer"]), job_id=job_id,
    ))
    await session.commit()
