"""Bounded lagen.nu document retrieval. Ingest stays serial.

Interpret overlaps under ``research_document_concurrency``. Graph
write-back is queued during interpret and flushed after every document
for the source has been interpreted.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TextUnitRecord
from app.llm.legal_research import LegalDomainExtractionError
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.lagen_nu.mcp_client import (
    LagenNuMcpClient,
    OfficialLagenNuMcpError,
    OfficialLagenNuMcpNotFoundError,
)
from app.services.lagen_nu.models import LagenNuDocument
from app.services.lagen_nu.passage_router import PassageRoutingError
from app.services.lagen_nu.text_unit_research import (
    LagenNuResearchKnowledgeError,
    current_lagen_nu_units,
    document_identity_uri,
    ingest_and_load_text_units,
    require_lagen_nu_research_knowledge,
)
from app.services.research.concurrency import map_with_limit, research_concurrency
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed

logger = logging.getLogger(__name__)

MAX_DOCUMENT_FETCHES = 5
MAX_DOCUMENT_CHARS = 200000


class DocumentFetchBudget(Protocol):
    remaining: int
    calls: list[dict[str, object]]


class DocumentFetchHost(Protocol):
    provider_id: str
    _session: AsyncSession | None
    _embeddings: EmbeddingProvider | None
    _vector_store: KnowledgeVectorStore | None

    def _mcp(self) -> LagenNuMcpClient: ...


@dataclass(frozen=True)
class DocumentFetchPlan:
    need: ResearchNeed
    context: ResearchContext
    candidates: Sequence[object]
    budget: DocumentFetchBudget
    source: str
    terms: frozenset[str]
    resolve_target: Callable[[object], tuple[str | None, str | None]]


@dataclass(frozen=True)
class _Work:
    host: DocumentFetchHost
    plan: DocumentFetchPlan
    session: AsyncSession
    embeddings: EmbeddingProvider
    vector_store: KnowledgeVectorStore
    customer_id: int


@dataclass
class _Slot:
    candidate: object
    canonical_uri: str
    pinpoint: str | None
    units: list[TextUnitRecord] | None = None
    document: LagenNuDocument | None = None
    reused_units: bool = False
    needs_fetch: bool = False
    early_evidence: ResearchEvidence | None = None
    fetch_error: OfficialLagenNuMcpError | None = None


def reserve_mcp_call(
    budget: DocumentFetchBudget,
    tool: str,
    arguments: dict[str, object],
) -> None:
    if budget.remaining <= 0:
        raise OfficialLagenNuMcpError("lagen.nu MCP call bound reached")
    budget.remaining -= 1
    budget.calls.append({"tool": tool, "arguments": dict(arguments)})


async def fetch_ranked_documents(
    host: DocumentFetchHost,
    plan: DocumentFetchPlan,
) -> list[ResearchEvidence]:
    session, embeddings, vector_store = require_lagen_nu_research_knowledge(
        session=host._session,
        embeddings=host._embeddings,
        vector_store=host._vector_store,
    )
    customer_id = plan.context.scope.customer_id
    if customer_id is None:
        raise LagenNuResearchKnowledgeError("lagen.nu research requires customer_id")
    work = _Work(
        host=host,
        plan=plan,
        session=session,
        embeddings=embeddings,
        vector_store=vector_store,
        customer_id=customer_id,
    )
    slots = await _prepare_slots(work)
    await _fetch_missing_documents(work, slots)
    await _ingest_slots(work, slots)
    return await map_with_limit(
        research_concurrency().documents,
        slots,
        lambda slot: _materialize_slot(work, slot),
    )


async def _prepare_slots(work: _Work) -> list[_Slot]:
    slots: list[_Slot] = []
    seen: set[str] = set()
    for candidate in work.plan.candidates:
        if len(slots) >= MAX_DOCUMENT_FETCHES or work.plan.budget.remaining <= 0:
            break
        slot = await _prepare_slot(work, candidate, seen)
        if slot is not None:
            slots.append(slot)
    return slots


async def _prepare_slot(work: _Work, candidate: object, seen: set[str]) -> _Slot | None:
    uri, pinpoint = work.plan.resolve_target(candidate)
    if uri is None:
        return None
    try:
        canonical_uri = document_identity_uri(uri)
    except LagenNuResearchKnowledgeError as exc:
        return _Slot(
            candidate=candidate,
            canonical_uri=uri,
            pinpoint=pinpoint,
            early_evidence=work.host._failure(
                work.plan.need,
                work.plan.budget,
                "unsupported_source_shape",
                uri,
                str(exc),
            ),
        )
    target_key = canonical_uri if pinpoint is None else f"{canonical_uri}#{pinpoint}"
    if target_key in seen:
        return None
    seen.add(target_key)
    units = await current_lagen_nu_units(
        work.session,
        customer_id=work.customer_id,
        canonical_uri=canonical_uri,
    )
    slot = _Slot(
        candidate=candidate,
        canonical_uri=canonical_uri,
        pinpoint=pinpoint,
        units=units,
        reused_units=units is not None,
    )
    if units is not None:
        return slot
    reserve_mcp_call(
        work.plan.budget,
        "get_document",
        {
            "uri": canonical_uri,
            "pinpoint": None,
            "max_chars": MAX_DOCUMENT_CHARS,
        },
    )
    slot.needs_fetch = True
    return slot


async def _fetch_missing_documents(work: _Work, slots: list[_Slot]) -> None:
    pending = [slot for slot in slots if slot.needs_fetch]
    if not pending:
        return
    logger.info(
        "provider_retrieval_started provider=%s documents=%s",
        work.host.provider_id,
        len(pending),
    )
    if work.session.in_transaction():
        await work.session.commit()
    await map_with_limit(
        research_concurrency().documents,
        pending,
        lambda slot: _fetch_one_document(work.host, slot),
    )


async def _fetch_one_document(host: DocumentFetchHost, slot: _Slot) -> _Slot:
    try:
        slot.document = await host._mcp().get_document(
            slot.canonical_uri,
            pinpoint=None,
            max_chars=MAX_DOCUMENT_CHARS,
        )
    except OfficialLagenNuMcpError as exc:
        slot.fetch_error = exc
    return slot


async def _ingest_slots(work: _Work, slots: list[_Slot]) -> None:
    for slot in slots:
        if slot.early_evidence is not None or slot.fetch_error is not None:
            continue
        try:
            slot.units = await _units_for_slot(work, slot)
        except (
            OfficialLagenNuMcpError,
            LegalDomainExtractionError,
            LagenNuResearchKnowledgeError,
            PassageRoutingError,
        ) as exc:
            slot.early_evidence = _slot_exception_evidence(work, slot, exc)


async def _materialize_slot(work: _Work, slot: _Slot) -> ResearchEvidence:
    if slot.early_evidence is not None:
        return slot.early_evidence
    if slot.fetch_error is not None:
        return _mcp_failure(work, slot, slot.fetch_error)
    try:
        units = slot.units
        if units is None:
            raise LagenNuResearchKnowledgeError("retrieved document is missing")
        return await work.host._from_document(
            work.plan.need,
            work.plan.context,
            slot.candidate,
            units,
            work.plan.budget,
            terms=work.plan.terms,
            canonical_uri=slot.canonical_uri,
            pinpoint=slot.pinpoint,
            document=slot.document,
            reused_units=slot.reused_units,
        )
    except (
        OfficialLagenNuMcpError,
        LegalDomainExtractionError,
        LagenNuResearchKnowledgeError,
        PassageRoutingError,
    ) as exc:
        return _slot_exception_evidence(work, slot, exc)


def _slot_exception_evidence(
    work: _Work,
    slot: _Slot,
    exc: (
        OfficialLagenNuMcpError
        | LegalDomainExtractionError
        | LagenNuResearchKnowledgeError
        | PassageRoutingError
    ),
) -> ResearchEvidence:
    if isinstance(exc, OfficialLagenNuMcpError):
        return _mcp_failure(work, slot, exc)
    if isinstance(exc, LagenNuResearchKnowledgeError):
        return work.host._failure(
            work.plan.need,
            work.plan.budget,
            "fetch_failed",
            slot.canonical_uri,
            str(exc),
        )
    return work.host._failure(
        work.plan.need,
        work.plan.budget,
        exc.category,
        slot.canonical_uri,
        str(exc),
        fetch_success=True,
    )


def _mcp_failure(
    work: _Work,
    slot: _Slot,
    exc: OfficialLagenNuMcpError,
) -> ResearchEvidence:
    category = (
        "resolve_no_document"
        if isinstance(exc, OfficialLagenNuMcpNotFoundError)
        else getattr(exc, "category", "fetch_failed")
    )
    return work.host._failure(
        work.plan.need,
        work.plan.budget,
        category,
        slot.canonical_uri,
        str(exc),
    )


async def _units_for_slot(work: _Work, slot: _Slot) -> list[TextUnitRecord]:
    if slot.units is not None:
        return slot.units
    document = slot.document
    if document is None:
        raise LagenNuResearchKnowledgeError("retrieved document is missing")
    if document.source and document.source != work.plan.source:
        raise LegalDomainExtractionError(
            f"expected source {work.plan.source}, received {document.source}",
            category="unsupported_source_shape",
        )
    ingest_result, units = await ingest_and_load_text_units(
        work.session,
        customer_id=work.customer_id,
        document=document,
        embeddings=work.embeddings,
        vector_store=work.vector_store,
    )
    if ingest_result.status != "indexed" or units is None:
        raise LegalDomainExtractionError(
            ingest_result.message or "retrieved document has no text",
            category="unsupported_source_shape",
        )
    return units
