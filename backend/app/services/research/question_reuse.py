"""Read-through and write-back for persistent Question → Evidence links.

Runtime needs canonicalize to KnowledgeQuestion first. Fresh grounded
claims close their source type. Excerpt hits stay candidates. Graph
outage must not fail the Attempt or invent a sufficient outcome.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    CanonicalDocumentRecord,
    DomainResearchResultRecord,
    TextUnitRecord,
)
from app.services.knowledge.claims import (
    KnowledgeClaimAnswerHit,
    KnowledgeClaimError,
    claim_answers_for_question_key,
)
from app.services.legal_research_result import LegalResearchResult
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
    research_question_key,
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


def classify_claim_freshness(
    *,
    observed_at: datetime | None,
    stored: Freshness | None = None,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> Freshness:
    """Grounded claims stay reusable until marked stale or aged out."""
    if stored == "stale":
        return "stale"
    if max_age_seconds is None:
        return "fresh"
    return classify_freshness(
        observed_at=observed_at,
        retrieved_at=observed_at,
        stored=stored,
        now=now,
        max_age_seconds=max_age_seconds,
    )


def is_claim_backed(item: ResearchEvidence) -> bool:
    raw = item.metadata.get("knowledge_claim_ids")
    return isinstance(raw, list) and any(
        isinstance(claim_id, str) and claim_id.strip() for claim_id in raw
    )


def _reuse_freshness(item: ResearchEvidence) -> Freshness | None:
    raw = item.metadata.get("reuse")
    if not isinstance(raw, dict):
        return None
    freshness = raw.get("freshness")
    if freshness in {"fresh", "stale", "unknown"}:
        return freshness
    return None


def covered_source_types(reused: Sequence[ResearchEvidence]) -> set[str]:
    """Source types already answered by fresh grounded claims."""
    covered: set[str] = set()
    for item in reused:
        if item.status != "found":
            continue
        if _reuse_freshness(item) != "fresh":
            continue
        if not is_claim_backed(item):
            continue
        if item.source_type:
            covered.add(item.source_type)
    return covered


def gap_source_types(
    need: ResearchNeed,
    reused: Sequence[ResearchEvidence],
) -> list[str]:
    covered = covered_source_types(reused)
    return [item for item in need.source_types if item not in covered]


def research_need_for_gaps(
    need: ResearchNeed,
    gaps: Sequence[str],
) -> ResearchNeed:
    return replace(need, source_types=list(gaps))


def should_skip_providers(
    need: ResearchNeed,
    reused: Sequence[ResearchEvidence],
) -> bool:
    """Skip live retrieval when fresh claims cover every requested source type.

    Excerpt-only reuse stays a candidate. It does not close a gap.
    """
    if not need.source_types:
        return False
    return not gap_source_types(need, reused)


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


def link_to_research_evidence(
    need: ResearchNeed,
    link: QuestionEvidenceLink,
    *,
    freshness: Freshness,
    question_id: str,
    legal_result: LegalResearchResult | None = None,
) -> ResearchEvidence:
    metadata = dict(link.provenance)
    metadata.pop("domain_result_id", None)
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
        legal_result=legal_result,
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
        raise QuestionEvidenceGraphError("Question→Evidence lookup requires customer_id")
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
            domain_record = None
            domain_id = link.provenance.get("domain_result_id")
            if isinstance(domain_id, str):
                domain_record = await session.get(DomainResearchResultRecord, domain_id)
            legal_result = (
                LegalResearchResult.model_validate(
                    {
                        **domain_record.result,
                        "raw_text": domain_record.raw_source.raw_text,
                    }
                )
                if domain_record is not None and domain_record.domain == "legal"
                else None
            )
            reused.append(
                link_to_research_evidence(
                    need,
                    link,
                    freshness=freshness,
                    question_id=question.id,
                    legal_result=legal_result,
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


def _scope_provenance(context: ResearchContext, source_type: str | None) -> dict[str, object]:
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
    """Graph outage drops excerpt candidates. Claim lookup is independent."""
    excerpts: list[ResearchEvidence] = []
    try:
        excerpts = await lookup_reusable_evidence(
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
    claims: list[ResearchEvidence] = []
    if context.scope.customer_id is not None:
        try:
            claims = await lookup_reusable_claims(
                session,
                need=need,
                context=context,
                now=now,
                max_age_seconds=max_age_seconds,
            )
        except SQLAlchemyError:
            await session.rollback()
    return _merge_reuse_candidates(excerpts, claims)


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
        tenant_question_scope(customer_id),
    )


async def safe_canonicalize_research_need(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    need: ResearchNeed,
    context: ResearchContext,
) -> KnowledgeQuestion | None:
    """Graph outage → no canonical row. Retrieval still runs."""
    try:
        return await canonicalize_research_need(
            session,
            graph=graph,
            need=need,
            context=context,
        )
    except (QuestionEvidenceGraphError, SQLAlchemyError):
        await session.rollback()
        return None


async def lookup_reusable_claims(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
    now: datetime | None = None,
    max_age_seconds: int | None = None,
) -> list[ResearchEvidence]:
    """KnowledgeQuestion answers: Claim → SUPPORTED_BY → TextUnit."""
    customer_id = context.scope.customer_id
    if customer_id is None:
        raise KnowledgeClaimError("claim reuse requires customer_id")
    age = (
        settings.research_knowledge_freshness_max_age_seconds
        if max_age_seconds is None
        else max_age_seconds
    )
    hits = await claim_answers_for_question_key(
        session,
        customer_id=customer_id,
        question_key=research_question_key(need.question),
    )
    reused: list[ResearchEvidence] = []
    for hit in hits:
        if not _matches_need_source(hit.source_type, need):
            continue
        reused.append(
            await _claim_hit_to_evidence(
                session,
                need=need,
                hit=hit,
                freshness=classify_claim_freshness(
                    observed_at=hit.created_at,
                    now=now,
                    max_age_seconds=age,
                ),
            )
        )
    return reused


async def _claim_hit_to_evidence(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    hit: KnowledgeClaimAnswerHit,
    freshness: Freshness,
) -> ResearchEvidence:
    document = await session.get(CanonicalDocumentRecord, hit.claim.document_id)
    if document is None:
        raise KnowledgeClaimError(
            f"claim {hit.claim.id} document {hit.claim.document_id} is missing"
        )
    units = await _supporting_units(session, hit.claim.supporting_text_unit_ids)
    excerpt = "\n\n".join(unit.text for unit in units)
    evidence_ref = hit.claim.id
    return research_evidence(
        research_need_id=need.id,
        source_type=hit.source_type,
        status="found",
        title=document.title,
        excerpt=excerpt,
        locator=",".join(hit.claim.supporting_text_unit_ids),
        source_id=hit.claim.document_id,
        source_url=document.canonical_uri,
        provider="knowledge_claim",
        retrieved_at=hit.created_at,
        metadata={
            "knowledge_claim_ids": [hit.claim.id],
            "supporting_text_unit_ids": list(hit.claim.supporting_text_unit_ids),
            "document_version_id": hit.claim.document_version_id,
            "answered_by_question_key": research_question_key(need.question),
            "reuse": reuse_lineage(
                origin=REUSE_ORIGIN_PERSISTENT,
                knowledge_question_id=hit.knowledge_question_id,
                evidence_ref=evidence_ref,
                freshness=freshness,
            ),
        },
    )


async def _supporting_units(
    session: AsyncSession,
    unit_ids: Sequence[str],
) -> list[TextUnitRecord]:
    if not unit_ids:
        raise KnowledgeClaimError("claim reuse requires SUPPORTED_BY TextUnits")
    rows = list(
        (
            await session.execute(
                select(TextUnitRecord).where(TextUnitRecord.id.in_(list(unit_ids)))
            )
        ).scalars()
    )
    by_id = {row.id: row for row in rows}
    missing = [unit_id for unit_id in unit_ids if unit_id not in by_id]
    if missing:
        raise KnowledgeClaimError(
            f"claim SUPPORTED_BY TextUnits are missing: {', '.join(missing)}"
        )
    return [by_id[unit_id] for unit_id in unit_ids]


def _merge_reuse_candidates(
    excerpts: Sequence[ResearchEvidence],
    claims: Sequence[ResearchEvidence],
) -> list[ResearchEvidence]:
    seen: set[str] = set()
    merged: list[ResearchEvidence] = []
    for item in [*claims, *excerpts]:
        ref = _item_evidence_ref(item)
        key = ref or item.evidence_id
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


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
