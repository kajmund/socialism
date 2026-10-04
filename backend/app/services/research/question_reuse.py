"""Canonical question identity and evidence lineage; reads use Graph v2 only."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution.snapshots import snapshot_research_evidence
from app.services.research.evidence_identity import (
    evidence_passage_id,
    evidence_source_id,
)
from app.services.research.knowledge_question import (
    KnowledgeQuestion,
    evidence_visibility,
    identity_from_text,
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
from app.services.research_domain_results import domain_result_id, raw_source_id

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
    kept = [item for item in reused if _item_evidence_ref(item) not in found_refs]
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


async def canonicalize_research_need(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
) -> KnowledgeQuestion:
    """Match or create the tenant KnowledgeQuestion before live retrieval."""
    customer_id = context.scope.customer_id
    if customer_id is None:
        raise QuestionEvidenceGraphError("KnowledgeQuestion canonicalize requires customer_id")
    return await graph.upsert_question(
        session,
        identity_from_text(need.question),
        tenant_question_scope(customer_id, context.scope.workspace_id),
    )


def _scope_provenance(context: ResearchContext, source_type: str | None) -> dict[str, object]:
    payload: dict[str, object] = {}
    if source_type in CASE_SCOPED_SOURCE_TYPES and context.scope.case_id is not None:
        payload[SCOPE_CASE_KEY] = context.scope.case_id
    if context.scope.module is not None:
        payload[SCOPE_MODULE_KEY] = context.scope.module
    return payload


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
    # Legal snapshots include their question-specific interpretation in the hash.
    # Write-back must reference that same passage, not an excerpt-only identity.
    content_hash = snapshot_research_evidence(evidence).content_hash
    assert content_hash is not None
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
        raw_id = raw_source_id(source_key, evidence.legal_result.raw_text)
        provenance["domain_result_id"] = domain_result_id(
            raw_id, evidence.research_need_id, evidence.legal_result
        )
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
        raise QuestionEvidenceGraphError("Question→Evidence upsert requires customer_id")
    identity = identity_from_text(need.question)
    tenant_question = await graph.upsert_question(
        session, identity, tenant_question_scope(customer_id, context.scope.workspace_id)
    )
    annotated: list[ResearchEvidence] = []
    for item in evidence:
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
        if item.status == "found" and not _has_reuse_lineage(item):
            annotated.append(attach_fresh_lineage(item, question_id=question_id, evidence_ref=ref))
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


async def commit_persisted_evidence(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
    evidence: Sequence[ResearchEvidence],
    source_attempt_id: str | None = None,
) -> list[ResearchEvidence]:
    """Commit write-back; failures propagate to the research worker."""
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
