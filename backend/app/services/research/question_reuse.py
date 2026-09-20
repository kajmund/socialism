"""Read-through and write-back for persistent Question → Evidence links.

Reuse is candidate retrieval. Local sufficiency still decides. Graph
outage must not fail the Attempt or invent a sufficient outcome.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.research.evidence_identity import (
    evidence_passage_id,
    evidence_source_id,
)
from app.services.research.knowledge_question import (
    KnowledgeQuestion,
    KnowledgeQuestionScope,
    evidence_visibility,
    identity_from_text,
    lookup_scopes,
    public_question_scope,
    stable_evidence_ref,
    tenant_question_scope,
)
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    research_evidence,
    utc_now,
)
from app.services.research.question_graph import (
    ANSWERED_BY,
    BESVARAS_AV,
    Freshness,
    QuestionEvidenceGraph,
    QuestionEvidenceGraphError,
    QuestionEvidenceLink,
    ReuseOrigin,
)

REUSE_ORIGIN_PERSISTENT: ReuseOrigin = "persistent_knowledge"
REUSE_ORIGIN_FRESH: ReuseOrigin = "fresh_retrieval"
SCOPE_CASE_KEY = "knowledge_case_id"
SCOPE_MODULE_KEY = "knowledge_module"
CASE_SCOPED_SOURCE_TYPES = frozenset({"case_knowledge"})


def classify_freshness(
    *,
    observed_at: datetime | None,
    retrieved_at: datetime | None,
    stored: Freshness | None = None,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> Freshness:
    """Re-checkable freshness. Unknown when age policy is absent — do not guess."""
    if stored == "stale":
        return "stale"
    stamp = observed_at or retrieved_at
    if stamp is None:
        return "unknown"
    if max_age_seconds is None:
        return "unknown"
    current = now or utc_now()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    age = (current - stamp).total_seconds()
    if age < 0:
        return "unknown"
    if age > max_age_seconds:
        return "stale"
    return "fresh"


def reuse_lineage(
    *,
    origin: ReuseOrigin,
    knowledge_question_id: str | None,
    evidence_ref: str,
    freshness: Freshness,
) -> dict[str, object]:
    return {
        "origin": origin,
        "knowledge_question_id": knowledge_question_id,
        "relation": ANSWERED_BY,
        "relation_sv": BESVARAS_AV,
        "freshness": freshness,
        "evidence_ref": evidence_ref,
    }


def should_skip_providers(
    need: ResearchNeed,
    reused: Sequence[ResearchEvidence],
) -> bool:
    """v1 never skips live retrieval.

    Graph hits are candidates. Production local assessment can be an LLM
    and now also sees evidence quality. A programmatic "found = sufficient"
    check must not become a parallel truth that under-researches.
    """
    del need, reused
    return False


def merge_reused_with_provider(
    reused: Sequence[ResearchEvidence],
    provider: Sequence[ResearchEvidence],
) -> list[ResearchEvidence]:
    """Keep unused candidates and prefer a live found hit for the same ref."""
    annotated = annotate_fresh_retrieval(provider)
    found_refs = {
        ref
        for item in annotated
        if item.status == "found"
        for ref in [_item_evidence_ref(item)]
        if ref is not None
    }
    kept = [
        item for item in reused if _item_evidence_ref(item) not in found_refs
    ]
    return [*kept, *annotated]


def _item_evidence_ref(item: ResearchEvidence) -> str | None:
    raw = item.metadata.get("reuse")
    if isinstance(raw, dict):
        ref = raw.get("evidence_ref")
        if isinstance(ref, str) and ref.strip():
            return ref.strip()
    return stable_evidence_ref(
        provider=item.provider,
        source_id=item.source_id,
        locator=item.locator,
        excerpt=item.excerpt,
    )


def link_to_research_evidence(
    need: ResearchNeed,
    link: QuestionEvidenceLink,
    *,
    freshness: Freshness,
    question_id: str,
) -> ResearchEvidence:
    from app.services.legal_research_result import LegalResearchResult

    metadata = dict(link.provenance)
    raw_legal = metadata.pop("legal_result", None)
    metadata["source_attempt_id"] = link.source_attempt_id
    metadata["reuse"] = reuse_lineage(
        origin=REUSE_ORIGIN_PERSISTENT,
        knowledge_question_id=question_id,
        evidence_ref=link.evidence_ref,
        freshness=freshness,
    )
    retrieved = link.retrieved_at or utc_now()
    return research_evidence(
        research_need_id=need.id,
        source_type=link.source_type or "unknown",
        status="found",
        title=link.title,
        excerpt=link.excerpt,
        locator=link.locator,
        source_id=link.source_id,
        source_url=link.source_url,
        provider=link.provider,
        retrieved_at=retrieved,
        metadata=metadata,
        legal_result=LegalResearchResult.model_validate(raw_legal) if raw_legal else None,
    )


def attach_fresh_lineage(
    evidence: ResearchEvidence,
    *,
    question_id: str | None,
    evidence_ref: str,
) -> ResearchEvidence:
    metadata = dict(evidence.metadata)
    metadata["reuse"] = reuse_lineage(
        origin=REUSE_ORIGIN_FRESH,
        knowledge_question_id=question_id,
        evidence_ref=evidence_ref,
        freshness="fresh",
    )
    return research_evidence(
        research_need_id=evidence.research_need_id,
        source_type=evidence.source_type,
        status=evidence.status,
        title=evidence.title,
        excerpt=evidence.excerpt,
        locator=evidence.locator,
        source_id=evidence.source_id,
        source_url=evidence.source_url,
        provider=evidence.provider,
        score=evidence.score,
        retrieved_at=evidence.retrieved_at,
        metadata=metadata,
        legal_result=evidence.legal_result,
    )


def _lookup_limit(limit: int | None) -> int:
    value = settings.research_knowledge_lookup_limit if limit is None else limit
    if value < 1:
        raise ValueError("research_knowledge_lookup_limit must be >= 1")
    return value


def annotate_fresh_retrieval(
    evidence: Sequence[ResearchEvidence],
) -> list[ResearchEvidence]:
    """Mark provider hits as fresh retrieval before they enter EvidenceSet."""
    annotated: list[ResearchEvidence] = []
    for item in evidence:
        if item.status == "found" and not _has_reuse_lineage(item):
            annotated.append(
                attach_fresh_lineage(
                    item,
                    question_id=None,
                    evidence_ref=stable_evidence_ref(
                        provider=item.provider,
                        source_id=item.source_id,
                        locator=item.locator,
                        excerpt=item.excerpt,
                    ),
                )
            )
            continue
        annotated.append(item)
    return annotated


async def lookup_reusable_evidence(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
    limit: int | None = None,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
    exclude_attempt_id: str | None = None,
) -> list[ResearchEvidence]:
    """Bounded one-hop lookup. Scope isolation is mandatory."""
    customer_id = context.scope.customer_id
    if customer_id is None:
        raise QuestionEvidenceGraphError(
            "Question→Evidence lookup requires customer_id"
        )
    identity = identity_from_text(need.question)
    bound = _lookup_limit(limit)
    age = (
        settings.research_knowledge_freshness_max_age_seconds
        if max_age_seconds is None
        else max_age_seconds
    )
    seen_refs: set[str] = set()
    reused: list[ResearchEvidence] = []
    for scope in lookup_scopes(customer_id):
        question = await graph.match_question(session, identity, scope)
        if question is None:
            continue
        remaining = bound - len(reused)
        if remaining < 1:
            break
        links = await graph.lookup_answers(
            session,
            question=question,
            limit=remaining,
            exclude_attempt_id=exclude_attempt_id,
        )
        for link in links:
            if link.evidence_ref in seen_refs:
                continue
            if not _link_allowed(
                link,
                need=need,
                context=context,
                customer_id=customer_id,
                scope=scope,
            ):
                continue
            seen_refs.add(link.evidence_ref)
            freshness = classify_freshness(
                observed_at=link.observed_at,
                retrieved_at=link.retrieved_at,
                stored=link.freshness,
                now=now,
                max_age_seconds=age,
            )
            reused.append(
                link_to_research_evidence(
                    need,
                    link,
                    freshness=freshness,
                    question_id=question.id,
                )
            )
    return reused


def _matches_need_source(source_type: str | None, need: ResearchNeed) -> bool:
    allowed = {item for item in need.source_types}
    if not allowed:
        return False
    return (source_type or "") in allowed


def _link_allowed(
    link: QuestionEvidenceLink,
    *,
    need: ResearchNeed,
    context: ResearchContext,
    customer_id: int,
    scope: KnowledgeQuestionScope,
) -> bool:
    if not _matches_need_source(link.source_type, need):
        return False
    if scope.visibility == "public":
        return link.visibility == "public"
    if scope.customer_id != customer_id:
        return False
    stored_case = _provenance_text(link.provenance, SCOPE_CASE_KEY)
    if stored_case is not None and stored_case != context.scope.case_id:
        return False
    stored_module = _provenance_text(link.provenance, SCOPE_MODULE_KEY)
    return stored_module is None or stored_module == context.scope.module


def _provenance_text(provenance: dict[str, object], key: str) -> str | None:
    value = provenance.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _scope_provenance(
    context: ResearchContext, source_type: str | None
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if source_type in CASE_SCOPED_SOURCE_TYPES and context.scope.case_id is not None:
        payload[SCOPE_CASE_KEY] = context.scope.case_id
    if context.scope.module is not None:
        payload[SCOPE_MODULE_KEY] = context.scope.module
    return payload


async def safe_lookup_reusable_evidence(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
    limit: int | None = None,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
    exclude_attempt_id: str | None = None,
) -> list[ResearchEvidence]:
    """Graph outage → empty candidates. Never a false success."""
    try:
        return await lookup_reusable_evidence(
            session,
            graph=graph,
            need=need,
            context=context,
            limit=limit,
            now=now,
            max_age_seconds=max_age_seconds,
            exclude_attempt_id=exclude_attempt_id,
        )
    except (QuestionEvidenceGraphError, SQLAlchemyError):
        await session.rollback()
        return []


def evidence_to_link(
    question: KnowledgeQuestion,
    evidence: ResearchEvidence,
    *,
    context: ResearchContext | None = None,
    observed_at: datetime | None = None,
    freshness: Freshness = "fresh",
    source_attempt_id: str | None = None,
) -> QuestionEvidenceLink | None:
    if evidence.status != "found":
        return None
    visibility = evidence_visibility(evidence.metadata)
    if question.scope.visibility == "public" and visibility != "public":
        return None
    if question.scope.visibility == "tenant" and visibility == "public":
        # Tenant question may still record a public hit for that kund.
        visibility = "public"
    ref = stable_evidence_ref(
        provider=evidence.provider,
        source_id=evidence.source_id,
        locator=evidence.locator,
        excerpt=evidence.excerpt,
    )
    declared_hash = evidence.metadata.get("content_hash")
    content_hash = (
        declared_hash
        if isinstance(declared_hash, str) and declared_hash.strip()
        else hashlib.sha256((evidence.excerpt or "").encode()).hexdigest()
    )
    source_key = evidence_source_id(
        provider=evidence.provider,
        source_id=evidence.source_id,
        source_url=evidence.source_url,
        content_hash=content_hash,
    )
    passage_id = evidence_passage_id(
        source_key=source_key,
        source_id=evidence.source_id,
        locator=evidence.locator,
        content_hash=content_hash,
    )
    version = evidence.metadata.get("version")
    version_text = version if isinstance(version, str) else None
    provenance = dict(evidence.metadata)
    if evidence.legal_result is not None:
        provenance["legal_result"] = evidence.legal_result.model_dump(mode="json")
    if context is not None:
        provenance.update(_scope_provenance(context, evidence.source_type))
    return QuestionEvidenceLink(
        question_id=question.id,
        evidence_ref=ref,
        passage_id=passage_id,
        relation=ANSWERED_BY,
        title=evidence.title,
        excerpt=evidence.excerpt,
        locator=evidence.locator,
        source_id=evidence.source_id,
        source_url=evidence.source_url,
        source_type=evidence.source_type,
        provider=evidence.provider,
        provenance=provenance,
        retrieved_at=evidence.retrieved_at,
        observed_at=observed_at or utc_now(),
        freshness=freshness,
        version=version_text,
        visibility=visibility,
        source_attempt_id=source_attempt_id,
    )


async def upsert_persisted_evidence(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
    evidence: Sequence[ResearchEvidence],
    source_attempt_id: str | None = None,
) -> list[ResearchEvidence]:
    """Idempotent Question + ANSWERED_BY upsert after EvidenceSet persist."""
    customer_id = context.scope.customer_id
    if customer_id is None:
        raise QuestionEvidenceGraphError(
            "Question→Evidence upsert requires customer_id"
        )
    identity = identity_from_text(need.question)
    tenant_question = await graph.upsert_question(
        session, identity, tenant_question_scope(customer_id)
    )
    public_question: KnowledgeQuestion | None = None
    annotated: list[ResearchEvidence] = []
    for item in evidence:
        visibility = evidence_visibility(item.metadata)
        ref = stable_evidence_ref(
            provider=item.provider,
            source_id=item.source_id,
            locator=item.locator,
            excerpt=item.excerpt,
        )
        question_id = tenant_question.id
        if _reuse_origin(item) == REUSE_ORIGIN_PERSISTENT:
            annotated.append(item)
            continue
        if item.status == "found":
            tenant_link = evidence_to_link(
                tenant_question,
                item,
                context=context,
                source_attempt_id=source_attempt_id,
            )
            if tenant_link is not None:
                await graph.upsert_answer(session, tenant_link)
            if visibility == "public":
                if public_question is None:
                    public_question = await graph.upsert_question(
                        session, identity, public_question_scope()
                    )
                public_link = evidence_to_link(
                    public_question,
                    item,
                    context=context,
                    source_attempt_id=source_attempt_id,
                )
                if public_link is not None:
                    await graph.upsert_answer(session, public_link)
                question_id = public_question.id
        if item.status == "found" and not _has_reuse_lineage(item):
            annotated.append(
                attach_fresh_lineage(
                    item, question_id=question_id, evidence_ref=ref
                )
            )
        else:
            annotated.append(item)
    return annotated


def _reuse_origin(item: ResearchEvidence) -> ReuseOrigin | None:
    raw = item.metadata.get("reuse")
    if isinstance(raw, dict):
        origin = raw.get("origin")
        if origin in {REUSE_ORIGIN_PERSISTENT, REUSE_ORIGIN_FRESH}:
            return origin
    return None


def _has_reuse_lineage(item: ResearchEvidence) -> bool:
    return _reuse_origin(item) is not None


async def safe_upsert_persisted_evidence(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
    evidence: Sequence[ResearchEvidence],
    source_attempt_id: str | None = None,
) -> list[ResearchEvidence]:
    """Write-back failure must not fail the Attempt after evidence is persisted."""
    try:
        result = await upsert_persisted_evidence(
            session,
            graph=graph,
            need=need,
            context=context,
            evidence=evidence,
            source_attempt_id=source_attempt_id,
        )
        await session.commit()
        return result
    except (QuestionEvidenceGraphError, SQLAlchemyError):
        await session.rollback()
        return list(evidence)
