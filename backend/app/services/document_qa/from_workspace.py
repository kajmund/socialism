"""Enqueue a finished one-document workspace answer. Never opens OverGraph."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Job
from app.services.document_qa.outbox import enqueue_document_qa
from app.services.document_qa.types import (
    AnalysisContract,
    AnswerPostWrite,
    QaWrite,
    SourceCite,
)
from app.services.graph_v2.errors import PermanentGraphError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkspaceQuestion:
    customer_id: int
    workspace_id: str
    question: str
    document_id: str
    document_version_id: str
    source_object_id: str
    job_id: str


@dataclass(frozen=True)
class WorkspaceQaSeed:
    customer_id: int
    workspace_id: str
    question: str
    document_id: str
    document_version_id: str
    created_at: str
    answer: str
    citations: tuple[Mapping[str, object], ...]
    job_id: str


def workspace_analysis_contract() -> AnalysisContract:
    model = settings.selected_llm_model
    return AnalysisContract(
        kind="document_chat",
        method="workspace_research",
        model=model,
        model_version=model,
        examined_scope="retrieved_evidence",
    )


def workspace_question(job: Job) -> WorkspaceQuestion | None:
    manifest = _manifest(job)
    if len(manifest) != 1:
        return None
    row = manifest[0]
    document_id = str(row.get("document_id") or "")
    version_id = str(row.get("document_version_id") or "")
    workspace_id = str(row.get("workspace_id") or job.request.get("workspace_id") or "")
    question = str(job.request.get("question") or "").strip()
    source_object_id = str(row.get("source_object_id") or "")
    if not document_id or not version_id or not workspace_id or not question:
        return None
    return WorkspaceQuestion(
        customer_id=job.customer_id,
        workspace_id=workspace_id,
        question=question,
        document_id=document_id,
        document_version_id=version_id,
        source_object_id=source_object_id,
        job_id=job.id,
    )


def workspace_qa_seed(job: Job, result: Mapping[str, object]) -> WorkspaceQaSeed | None:
    asked = workspace_question(job)
    answer = str(result.get("answer") or "").strip()
    citations = result.get("citations")
    if asked is None or not answer or not isinstance(citations, list):
        return None
    return WorkspaceQaSeed(
        customer_id=asked.customer_id,
        workspace_id=asked.workspace_id,
        question=asked.question,
        document_id=asked.document_id,
        document_version_id=asked.document_version_id,
        created_at=_stamp(job.created_at),
        answer=answer,
        citations=tuple(item for item in citations if isinstance(item, dict)),
        job_id=asked.job_id,
    )


def qa_write_from_seed(seed: WorkspaceQaSeed) -> QaWrite | None:
    cites = tuple(
        cite
        for item in seed.citations
        if (cite := _cite(item, seed.document_version_id)) is not None
    )
    if not cites:
        return None
    return QaWrite(
        question_text=seed.question,
        document_id=seed.document_id,
        document_version_id=seed.document_version_id,
        workspace_id=seed.workspace_id,
        contract=workspace_analysis_contract(),
        status="ANSWERED",
        answer_text=seed.answer,
        posts=(AnswerPostWrite(seed.answer, cites),),
        asked_at=seed.created_at,
        created_at=seed.created_at,
        embedding=None,
    )


async def enqueue_workspace_document_answer(
    session: AsyncSession, seed: WorkspaceQaSeed | None,
) -> str | None:
    if seed is None:
        return None
    write = qa_write_from_seed(seed)
    if write is None:
        return None
    try:
        work_id = await enqueue_document_qa(
            session, customer_id=seed.customer_id, write=write,
        )
        await session.commit()
    except (PermanentGraphError, ValueError, TypeError, KeyError):
        logger.exception("document_qa.workspace_enqueue_failed job_id=%s", seed.job_id)
        await session.rollback()
        return None
    return work_id


def _manifest(job: Job) -> list[dict[str, object]]:
    raw = job.request.get("document_manifest") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _cite(item: Mapping[str, object], version_id: str) -> SourceCite | None:
    if str(item.get("document_version_id") or "") != version_id:
        return None
    unit = str(item.get("text_unit_id") or "")
    excerpt = str(item.get("excerpt") or "").strip()
    if not unit or not excerpt:
        return None
    return SourceCite(unit, excerpt)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
