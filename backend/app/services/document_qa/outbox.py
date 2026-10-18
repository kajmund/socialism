"""Enqueue a durable Q&A job. This module never opens OverGraph."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphIngestWork
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.document_qa.access import Viewer, require_customer_id
from app.services.document_qa.kinds import DOCUMENT_QA_WRITE
from app.services.document_qa.normalize import normalize_question, reuse_digest
from app.services.document_qa.types import (
    AnalysisContract,
    AnswerPostWrite,
    QaWrite,
    SourceCite,
)
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.identity import stable_id


async def enqueue_document_qa(
    session: AsyncSession, *, customer_id: int, write: QaWrite,
) -> str:
    customer_id = require_customer_id(customer_id)
    await require_owned_version(session, customer_id, write)
    digest = reuse_digest(
        normalize_question(write.question_text), write.document_version_id, write.contract,
    )
    work_id = stable_id(DOCUMENT_QA_WRITE, str(customer_id), digest, write.created_at)
    payload = qa_payload(write)
    try:
        async with session.begin_nested():
            session.add(GraphIngestWork(
                id=work_id,
                customer_id=customer_id,
                scope_key=f"customer:{customer_id}",
                payload=payload,
                status="pending",
                attempts=0,
            ))
            await session.flush()
    except IntegrityError:
        if await session.get(GraphIngestWork, work_id) is None:
            raise
    return work_id


async def require_owned_version(
    session: AsyncSession, customer_id: int, write: QaWrite,
) -> None:
    await require_owned_ids(
        session, customer_id, write.document_id, write.document_version_id,
    )


async def require_owned_ids(
    session: AsyncSession, customer_id: int, document_id: str, version_id: str,
) -> None:
    document = await session.get(CanonicalDocumentRecord, document_id)
    version = await session.get(DocumentVersionRecord, version_id)
    if document is None or version is None:
        raise PermanentGraphError("document version is missing")
    if document.customer_id != customer_id or version.customer_id != customer_id:
        raise PermanentGraphError("document version is outside the verified tenant")
    if version.document_id != document.id:
        raise PermanentGraphError("document version does not belong to the document")


def qa_payload(write: QaWrite) -> dict[str, object]:
    return {
        "kind": DOCUMENT_QA_WRITE,
        "workspace_id": write.workspace_id,
        "document_id": write.document_id,
        "document_version_id": write.document_version_id,
        "question_text": write.question_text,
        "status": write.status,
        "answer_text": write.answer_text,
        "asked_at": write.asked_at,
        "created_at": write.created_at,
        "contract": {
            "kind": write.contract.kind,
            "method": write.contract.method,
            "model": write.contract.model,
            "model_version": write.contract.model_version,
            "examined_scope": write.contract.examined_scope,
            "question_context": write.contract.question_context,
        },
        "posts": [
            {
                "text": post.text,
                "sources": [
                    {
                        "text_unit_id": cite.text_unit_id,
                        "excerpt": cite.excerpt,
                        "start": cite.start,
                        "end": cite.end,
                        "position_validated": cite.position_validated,
                    }
                    for cite in post.sources
                ],
            }
            for post in write.posts
        ],
        "embedding": list(write.embedding) if write.embedding is not None else None,
    }


def qa_from_payload(payload: dict[str, object], customer_id: int) -> tuple[Viewer, QaWrite]:
    contract_raw = payload.get("contract")
    if not isinstance(contract_raw, dict):
        raise PermanentGraphError("document_qa_write is missing a contract")
    posts_raw = payload.get("posts")
    if not isinstance(posts_raw, list) or not posts_raw:
        raise PermanentGraphError("document_qa_write is missing answer posts")
    write = QaWrite(
        question_text=str(payload.get("question_text") or ""),
        document_id=str(payload.get("document_id") or ""),
        document_version_id=str(payload.get("document_version_id") or ""),
        workspace_id=str(payload.get("workspace_id") or ""),
        contract=AnalysisContract(
            kind=str(contract_raw.get("kind") or ""),
            method=str(contract_raw.get("method") or ""),
            model=str(contract_raw.get("model") or ""),
            model_version=str(contract_raw.get("model_version") or ""),
            examined_scope=str(contract_raw.get("examined_scope") or ""),
            question_context=str(contract_raw.get("question_context") or ""),
        ),
        status=str(payload.get("status") or ""),
        answer_text=str(payload.get("answer_text") or ""),
        posts=tuple(_post_from(item) for item in posts_raw),
        asked_at=str(payload.get("asked_at") or ""),
        created_at=str(payload.get("created_at") or ""),
        embedding=_embedding(payload.get("embedding")),
    )
    viewer = Viewer(
        customer_id=customer_id,
        workspace_id=write.workspace_id,
        readable_document_ids=frozenset({write.document_id}),
        readable_version_ids=frozenset({write.document_version_id}),
    )
    return viewer, write


def _post_from(item: object) -> AnswerPostWrite:
    if not isinstance(item, dict):
        raise PermanentGraphError("document_qa_write post is invalid")
    sources = item.get("sources") or []
    if not isinstance(sources, list):
        raise PermanentGraphError("document_qa_write sources are invalid")
    return AnswerPostWrite(
        text=str(item.get("text") or ""),
        sources=tuple(_cite_from(cite) for cite in sources),
    )


def _cite_from(item: object) -> SourceCite:
    if not isinstance(item, dict):
        raise PermanentGraphError("document_qa_write source is invalid")
    return SourceCite(
        text_unit_id=str(item.get("text_unit_id") or ""),
        excerpt=str(item.get("excerpt") or ""),
        start=_optional_int(item.get("start")),
        end=_optional_int(item.get("end")),
        position_validated=bool(item.get("position_validated")),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PermanentGraphError("document_qa_write source position is invalid")
    return value


def _embedding(value: object) -> tuple[float, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise PermanentGraphError("document_qa_write embedding is invalid")
    return tuple(float(item) for item in value)
