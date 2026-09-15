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
from app.services.research.assessment import (
    AssessableEvidence,
    programmatic_assessment,
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
    ResearchPlan,
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


def _assessable(item: ResearchEvidence) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=item.evidence_id,
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        score=item.score,
        provenance=dict(item.metadata),
        retrieved_at=item.retrieved_at,
        content_hash=hashlib.sha256((item.excerpt or "").encode("utf-8")).hexdigest(),
    )


def should_skip_providers(
    need: ResearchNeed,
    reused: Sequence[ResearchEvidence],
) -> bool:
    """True only when existing local sufficiency is met by fresh reused found items."""
    if not reused:
        return False
    draft = programmatic_assessment(
        ResearchPlan(needs=[need]),
        [_assessable(item) for item in reused],
    )
    if draft.result != "sufficient":
        return False
    supporting_ids = {
        evidence_id
        for row in draft.need_assessments
        if row.research_need_id == need.id
        for evidence_id in row.supporting_evidence_ids
    }
    supporting = [item for item in reused if item.evidence_id in supporting_ids]
    if not supporting:
        return False
    return all(_item_freshness(item) == "fresh" for item in supporting)


def _item_freshness(item: ResearchEvidence) -> Freshness:
    raw = item.metadata.get("reuse")
    if isinstance(raw, dict):
        value = raw.get("freshness")
        if value in {"fresh", "stale", "unknown"}:
            return value
    return "unknown"


def link_to_research_evidence(
    need: ResearchNeed,
    link: QuestionEvidenceLink,
    *,
    freshness: Freshness,
    question_id: str,
) -> ResearchEvidence:
    metadata = dict(link.provenance)
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
            if not _link_allowed(link, customer_id=customer_id, scope=scope):
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


def _link_allowed(
    link: QuestionEvidenceLink,
    *,
    customer_id: int,
    scope: KnowledgeQuestionScope,
) -> bool:
    if scope.visibility == "public":
        return link.visibility == "public"
    return scope.customer_id == customer_id


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
        return []


def evidence_to_link(
    question: KnowledgeQuestion,
    evidence: ResearchEvidence,
    *,
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
    version = evidence.metadata.get("version")
    version_text = version if isinstance(version, str) else None
    return QuestionEvidenceLink(
        question_id=question.id,
        evidence_ref=ref,
        relation=ANSWERED_BY,
        title=evidence.title,
        excerpt=evidence.excerpt,
        locator=evidence.locator,
        source_id=evidence.source_id,
        source_url=evidence.source_url,
        source_type=evidence.source_type,
        provider=evidence.provider,
        provenance=dict(evidence.metadata),
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
        if item.status == "found":
            tenant_link = evidence_to_link(
                tenant_question, item, source_attempt_id=source_attempt_id
            )
            if tenant_link is not None:
                await graph.upsert_answer(session, tenant_link)
            if visibility == "public":
                if public_question is None:
                    public_question = await graph.upsert_question(
                        session, identity, public_question_scope()
                    )
                public_link = evidence_to_link(
                    public_question, item, source_attempt_id=source_attempt_id
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


def _has_reuse_lineage(item: ResearchEvidence) -> bool:
    raw = item.metadata.get("reuse")
    return isinstance(raw, dict) and raw.get("origin") in {
        REUSE_ORIGIN_PERSISTENT,
        REUSE_ORIGIN_FRESH,
    }


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
        return await upsert_persisted_evidence(
            session,
            graph=graph,
            need=need,
            context=context,
            evidence=evidence,
            source_attempt_id=source_attempt_id,
        )
    except (QuestionEvidenceGraphError, SQLAlchemyError):
        return list(evidence)
