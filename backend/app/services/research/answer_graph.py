"""Publish assessed, frozen answer episodes through the Overgraph owner."""

import hashlib
import json
from datetime import UTC, datetime
from dataclasses import asdict

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import DocumentVersionRecord, EvidenceSet, KnowledgeQuestionRow
from app.services.knowledge.scope import require_persist_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.owner_facts import publish_answer_via_owner
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.publish import AnswerPublish
from app.services.overgraph.answers import (
    ANSWER_PREDICATE as GRAPH_ANSWER_PREDICATE,
    answer_facts,
    current_fact,
    entity_attributes,
)
from app.services.research.graph_grounding import (
    fact_is_current,
    current_interval,
    GraphResearchError,
)
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    research_evidence,
)
from app.services.research.question_reuse import classify_freshness, reuse_lineage

from app.services.research.workspace_grounding import basis_workspace_allowed, manifest_matches

ANSWER_PREDICATE = GRAPH_ANSWER_PREDICATE
ANSWER_TYPE = "research.answer"
BASIS = TypeAdapter(list[ResearchEvidence])


async def publish_answer(
    session: AsyncSession,
    *,
    question: KnowledgeQuestionRow,
    context: ResearchContext,
    evidence_set_id: str,
    basis: list[ResearchEvidence],
    assessment: dict,
) -> str | None:
    frozen = await session.get(EvidenceSet, evidence_set_id)
    if frozen is None or frozen.status != "frozen" or not basis:
        return None
    scope = require_persist_scope(scope_type=question.scope_type, customer_id=question.customer_id)
    if scope.customer_id != context.scope.customer_id:
        raise GraphResearchError("Answer publication crossed its tenant boundary")
    payload = BASIS.dump_python(basis, mode="json")
    identity = hashlib.sha256(
        json.dumps(
            {
                "question_id": question.id,
                "scope": asdict(context.scope),
                "evidence_set_id": evidence_set_id,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    attributes = {
        "knowledge_module": context.scope.module,
        "knowledge_case_id": context.scope.case_id,
        "workspace_id": context.scope.workspace_id,
        "document_version_ids": list(context.scope.allowed_document_version_ids or ()),
        "answer_status": "sufficient" if assessment.get("sufficient") else "partial",
    }
    # Answers have no TextUnit anchor: identity is the explicit episode contract.
    # The owner writer resolves the question/answer entity keys from the same
    # shared identity builders the direct path used and commits one mutation.
    dependency_candidates = tuple(sorted({
        ref for item in basis for ref in item.metadata.get("graph_fact_ids", [])
    }))
    return await publish_answer_via_owner(
        get_owner_runtime().require_client(),
        AnswerPublish(
            question_id=question.id,
            question_text=question.display_text,
            scope=scope,
            identity=identity,
            evidence_set_id=evidence_set_id,
            attributes=attributes,
            basis=payload,
            assessment=assessment,
            dependency_ids=dependency_candidates,
        ),
    )


async def lookup_answers(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
    now: datetime,
) -> list[ResearchEvidence]:
    if not need.knowledge_question_id:
        return []
    scopes = ("shared", f"customer:{context.scope.customer_id}")
    catalog = require_knowledge()
    facts = await catalog.run(
        _answer_candidates, catalog, need.knowledge_question_id,
        context.scope.customer_id, now,
    )
    evidence = []
    seen = set()
    for fact in facts:
        if fact.scope_key not in scopes:
            continue
        if not fact_is_current(fact, now) or not _context_matches(fact, context):
            continue
        target = await catalog.run(entity_attributes, catalog, fact.target_id)
        if target is None or target.node_type != ANSWER_TYPE:
            continue
        if target.scope_key != fact.scope_key:
            raise GraphResearchError("Graph answer crossed its tenant boundary")
        basis = BASIS.validate_python(target.attributes.get("basis"))
        if not await basis_workspace_allowed(session, basis, context):
            continue
        if not await _current_basis(session, basis, fact.scope_key, now):
            continue
        for item in basis:
            ref = str(item.metadata.get("reuse", {}).get("evidence_ref") or item.evidence_id)
            if ref in seen or (
                item.source_type not in need.source_types and item.source_type != "derived"
            ):
                continue
            seen.add(ref)
            evidence.append(_rebind(item, need, fact, ref=ref, now=now))
    return evidence


def _context_matches(fact, context: ResearchContext) -> bool:
    return manifest_matches(fact, context) and fact.attributes.get("knowledge_module") == context.scope.module and (
        fact.attributes.get("knowledge_case_id") == context.scope.case_id
    )


def _answer_candidates(catalog, question_id, customer_id, now):
    return answer_facts(catalog, question_id, customer_id, now=now)


async def _current_basis(session, basis, scope_key, now) -> bool:
    max_age = settings.research_knowledge_freshness_max_age_seconds
    for item in basis:
        stamp = (
            item.retrieved_at.replace(tzinfo=UTC)
            if item.retrieved_at.tzinfo is None
            else item.retrieved_at
        )
        if stamp > now or item.metadata.get("reuse", {}).get("freshness") == "stale":
            return False
        if max_age is not None and (now - stamp).total_seconds() > max_age:
            return False
    fact_ids = {ref for item in basis for ref in item.metadata.get("graph_fact_ids", [])}
    version_ids = {ref for item in basis for ref in item.metadata.get("document_version_ids", [])}
    version_ids.update(
        item.metadata["document_version_id"]
        for item in basis
        if item.metadata.get("document_version_id")
    )
    catalog = require_knowledge()
    for fact_id in fact_ids:
        if not await catalog.run(current_fact, catalog, fact_id, scope_key, now):
            return False
    versions = (await session.execute(select(
        DocumentVersionRecord.id, DocumentVersionRecord.scope_key, DocumentVersionRecord.superseded_at,
        DocumentVersionRecord.valid_from, DocumentVersionRecord.valid_to,
    ).where(DocumentVersionRecord.id.in_(version_ids)))).all()
    if len(versions) != len(version_ids) or any(
        version.scope_key not in ("shared", scope_key) or version.superseded_at is not None
        or not current_interval(version.valid_from, version.valid_to, now)
        for version in versions
    ):
        return False
    return True


def _rebind(item, need, fact, *, ref, now):
    stamp = item.retrieved_at
    stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
    metadata = dict(item.metadata)
    metadata.update(
        {"answer_fact_id": fact.id, "previous_answer_status": fact.attributes["answer_status"]}
    )
    metadata["reuse"] = reuse_lineage(
        origin="persistent_knowledge",
        knowledge_question_id=need.knowledge_question_id,
        evidence_ref=ref,
        freshness="fresh"
        if settings.research_knowledge_freshness_max_age_seconds is None
        else classify_freshness(
            retrieved_at=stamp,
            observed_at=None,
            now=now,
            max_age_seconds=settings.research_knowledge_freshness_max_age_seconds,
        ),
    )
    return research_evidence(
        research_need_id=need.id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider="graph_v2",
        score=item.score,
        retrieved_at=stamp,
        metadata=metadata,
        legal_result=item.legal_result,
    )
