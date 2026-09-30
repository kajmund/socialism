"""Publish assessed, frozen answer episodes directly into Graph v2."""

import hashlib
import json
from datetime import UTC, datetime
from dataclasses import asdict

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.graph_v2 import GraphFact, GraphNode
from app.database.models import DocumentVersionRecord, EvidenceSet, KnowledgeQuestionRow
from app.services.graph_v2.questions import question_node
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.graph_v2.write import resolve_fact, resolve_node
from app.services.knowledge.scope import require_persist_scope
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

ANSWER_PREDICATE = "research.answered_by"
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
    source = await question_node(session, question)
    target = await resolve_node(
        session,
        NodeInput(
            node_type=ANSWER_TYPE,
            name=question.display_text,
            scope=scope,
            identifier_namespace="research.answer_id",
            identifier=identity,
            attributes={
                "basis": payload,
                "assessment": assessment,
                "evidence_set_id": evidence_set_id,
            },
        ),
    )
    fact, _decision = await resolve_fact(
        session,
        FactInput(
            source_id=source.id,
            target_id=target.id,
            scope=scope,
            predicate=ANSWER_PREDICATE,
            fact_text=question.display_text,
            sources=(SourceRef("episode", evidence_set_id),),
            occurrence_key=identity,
            attributes={
                "knowledge_module": context.scope.module,
                "knowledge_case_id": context.scope.case_id,
                "answer_status": "sufficient" if assessment.get("sufficient") else "partial",
            },
        ),
    )
    from app.services.graph_v2.revalidation import attach_question_dependency

    dependencies = {ref for item in basis for ref in item.metadata.get("graph_fact_ids", [])}
    for ref in dependencies:
        await attach_question_dependency(session, question_node_id=source.id, fact_id=ref)
    return fact.id


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
    nodes = list(
        await session.scalars(
            select(GraphNode).where(
                GraphNode.node_type == "core.question",
                GraphNode.scope_key.in_(scopes),
            )
        )
    )
    ids = [
        node.id
        for node in nodes
        if node.attributes.get("canonical_question_id") == need.knowledge_question_id
    ]
    rows = (
        await session.execute(
            select(GraphFact, GraphNode)
            .join(
                GraphNode,
                GraphNode.id == GraphFact.target_id,
            )
            .where(
                GraphFact.source_id.in_(ids),
                GraphFact.scope_key.in_(scopes),
                GraphFact.predicate == ANSWER_PREDICATE,
                GraphNode.node_type == ANSWER_TYPE,
                GraphFact.status == "active",
            )
            .order_by(GraphFact.created_at.desc())
        )
    ).all()
    evidence = []
    seen = set()
    for fact, node in rows:
        if not fact_is_current(fact, now) or not _context_matches(fact, context):
            continue
        if node.scope_key != fact.scope_key:
            raise GraphResearchError("Graph answer crossed its tenant boundary")
        basis = BASIS.validate_python(node.attributes.get("basis"))
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


def _context_matches(fact: GraphFact, context: ResearchContext) -> bool:
    return fact.attributes.get("knowledge_module") == context.scope.module and (
        fact.attributes.get("knowledge_case_id") == context.scope.case_id
    )


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
    for ref in fact_ids:
        fact = await session.get(GraphFact, ref)
        if (
            fact is None
            or fact.scope_key not in ("shared", scope_key)
            or not fact_is_current(fact, now)
        ):
            return False
    for ref in version_ids:
        version = await session.get(DocumentVersionRecord, ref)
        if version is None or version.scope_key not in ("shared", scope_key):
            return False
        if version.superseded_at is not None or not current_interval(
            version.valid_from, version.valid_to, now
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
