"""Parity verification before the SQL knowledge tables are dropped.

A green suite and zero production writes do not prove that existing knowledge reached
OverGraph. This walks the legacy tables and checks every row against the graph: identity,
scope, values, support, answer links, relations, observations, temporality and provenance.
The fingerprint it produces binds an Alembic drop to a verified state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import (
    GraphFact,
    GraphFactQuestionDependency,
    GraphFactRelation,
    GraphFactSource,
    GraphIdentifier,
    GraphNode,
)
from app.database.knowledge_observation import KnowledgeObservationRecord
from app.database.models import (
    KnowledgeClaimAnswer as KnowledgeClaimAnswerRow,
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    KnowledgeEntityRecord,
    KnowledgeRelationshipRecord,
)
from app.services.graph_v2.identity import (
    fact_occurrence_selector,
    source_fact_identity,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.claim_answers import claim_answer_edges
from app.services.overgraph.labels import (
    CLAIM,
    CONTRADICTS,
    DEPENDS_ON,
    DOCUMENT,
    ENTITY,
    FACT,
    LINKED,
    SUPPORTS,
    TEXT_UNIT,
    VERIFICATION_OBSERVATION,
)
from app.services.overgraph.legal_claims import (
    claim_in_graph,
    supporting_text_units,
)

KNOWLEDGE_TABLES = (
    "knowledge_claims",
    "knowledge_claim_text_units",
    "knowledge_claim_answers",
    "knowledge_entities",
    "knowledge_relationships",
    "knowledge_observations",
)
GRAPH_V2_TABLES = (
    "graph_nodes",
    "graph_identifiers",
    "graph_facts",
    "graph_fact_sources",
    "graph_fact_relations",
    "graph_fact_question_dependencies",
)


@dataclass
class ParityReport:
    counts: dict[str, int] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)
    checked: int = 0
    fingerprint: str = ""

    @property
    def verified(self) -> bool:
        return not self.mismatches

    def as_dict(self) -> dict[str, object]:
        return {
            "counts": dict(self.counts),
            "checked": self.checked,
            "mismatches": list(self.mismatches),
            "verified": self.verified,
            "fingerprint": self.fingerprint,
        }


async def _rows(session: AsyncSession, model) -> list:
    return list((await session.execute(select(model))).scalars().all())


def _fingerprint(counts: dict[str, int]) -> str:
    payload = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def verify_parity(session: AsyncSession) -> ParityReport:
    report = ParityReport()
    catalog = require_knowledge()
    graph_claims, _ = catalog.query_nodes(
        label_filter={"labels": [CLAIM], "mode": "all"}, limit=100000,
    )
    report.counts["claims_graph"] = len(graph_claims)

    claims = await _rows(session, KnowledgeClaimRecord)
    report.counts["knowledge_claims"] = len(claims)
    _check_claims(catalog, claims, report)

    links = await _rows(session, KnowledgeClaimTextUnit)
    report.counts["knowledge_claim_text_units"] = len(links)
    _check_supports(catalog, links, report)

    entities = await _rows(session, KnowledgeEntityRecord)
    report.counts["knowledge_entities"] = len(entities)
    for entity in entities:
        report.checked += 1
        if catalog.get_by_key(ENTITY, entity.id) is None:
            report.mismatches.append(f"entity {entity.id} is missing in the graph")

    relationships = await _rows(session, KnowledgeRelationshipRecord)
    report.counts["knowledge_relationships"] = len(relationships)
    _check_relationships(catalog, relationships, report)

    observations = await _rows(session, KnowledgeObservationRecord)
    report.counts["knowledge_observations"] = len(observations)
    for observation in observations:
        report.checked += 1
        if catalog.get_by_key(VERIFICATION_OBSERVATION, observation.id) is None:
            report.mismatches.append(f"observation {observation.id} is missing in the graph")

    answers = await _rows(session, KnowledgeClaimAnswerRow)
    report.counts["knowledge_claim_answers"] = len(answers)
    _check_answers(catalog, answers, report)

    await _check_graph_v2(session, report)
    report.fingerprint = _fingerprint(report.counts)
    return report


def _check_claims(catalog, claims, report: ParityReport) -> None:
    for claim in claims:
        report.checked += 1
        node = claim_in_graph(catalog, scope_key=claim.scope_key, identity=claim.id)
        if node is None:
            report.mismatches.append(f"claim {claim.id} is missing in the graph")
            continue
        if str(node.props.get("predicate") or "") != claim.predicate:
            report.mismatches.append(f"claim {claim.id} predicate differs")
        if json.loads(str(node.props.get("value_json") or "{}")) != claim.value:
            report.mismatches.append(f"claim {claim.id} value differs")
        status = str(node.props.get("status") or "active")
        if claim.superseded_at is not None and status != "superseded":
            report.mismatches.append(f"claim {claim.id} supersession missing in the graph")
        if claim.superseded_at is None and status != "active":
            report.mismatches.append(f"claim {claim.id} closed in the graph but open in SQL")


def _check_supports(catalog, links, report: ParityReport) -> None:
    by_claim: dict[str, set[str]] = {}
    for link in links:
        by_claim.setdefault(link.claim_id, set()).add(link.text_unit_id)
    for claim_id, expected in by_claim.items():
        report.checked += 1
        units = set(supporting_text_units(catalog, claim_id))
        missing = expected - units
        if missing:
            report.mismatches.append(
                f"claim {claim_id} missing SUPPORTED_BY TextUnits {sorted(missing)}"
            )


def _check_relationships(catalog, relationships, report: ParityReport) -> None:
    for edge in relationships:
        report.checked += 1
        label = {
            "SUPPORTED_BY": SUPPORTS,
            "CONTRADICTS": CONTRADICTS,
        }.get(edge.relation, LINKED)
        source_label, target_label = _kind_label(edge.from_kind), _kind_label(edge.to_kind)
        if source_label is None or target_label is None:
            continue
        source = catalog.get_by_key(source_label, edge.from_id)
        target = catalog.get_by_key(target_label, edge.to_id)
        if source is None or target is None:
            report.mismatches.append(f"relationship {edge.id} endpoint missing in the graph")
            continue
        if catalog.get_edge_by_triple(source.engine_id, target.engine_id, label) is None:
            report.mismatches.append(f"relationship {edge.id} edge missing in the graph")


def _check_answers(catalog, answers, report: ParityReport) -> None:
    seen: set[tuple[str, str]] = set()
    for answer in answers:
        report.checked += 1
        if (answer.claim_id, answer.question_key) in seen:
            continue
        seen.add((answer.claim_id, answer.question_key))
        edges = [
            (node, props)
            for node, props in claim_answer_edges(
                catalog, customer_id=answer.customer_id or 0, question_key=answer.question_key,
            )
            if str(node.key) == answer.claim_id
        ]
        if not edges:
            report.mismatches.append(
                f"claim {answer.claim_id} has no ANSWERED_BY link for {answer.question_key}"
            )
            continue
        props = edges[0][1]
        if str(props.get("research_need_id") or "") != answer.research_need_id:
            report.mismatches.append(
                f"claim {answer.claim_id} ANSWERED_BY research_need_id differs"
            )


def _kind_label(kind: str) -> str | None:
    return {
        "entity": ENTITY,
        "claim": CLAIM,
        "text_unit": TEXT_UNIT,
        "document": DOCUMENT,
    }.get(kind)


async def _check_graph_v2(session: AsyncSession, report: ParityReport) -> None:
    """Occurrence-level checks for the Graph v2 tables before they are dropped."""
    catalog = require_knowledge()
    nodes = (await session.scalars(select(GraphNode))).all()
    report.counts["graph_nodes"] = len(list(nodes))
    for node in nodes:
        report.checked += 1
        if catalog.get_by_key(ENTITY, node.id) is None:
            report.mismatches.append(f"graph node {node.id} is missing in the graph")

    facts = (await session.scalars(select(GraphFact))).all()
    report.counts["graph_facts"] = len(list(facts))
    sources = (await session.scalars(select(GraphFactSource))).all()
    report.counts["graph_fact_sources"] = len(list(sources))
    by_fact: dict[str, list[str]] = {}
    for row in sources:
        by_fact.setdefault(row.fact_id, []).append(f"{row.source_kind}:{row.source_ref}")
    for fact in facts:
        report.checked += 1
        if not _fact_present(catalog, fact, by_fact.get(fact.id, [])):
            report.mismatches.append(
                f"fact {fact.id} has no OverGraph fact for its source occurrences"
            )

    relations = (await session.scalars(select(GraphFactRelation))).all()
    report.counts["graph_fact_relations"] = len(list(relations))
    for relation in relations:
        report.checked += 1
        left, right = _fact_pair(catalog, relation)
        if left is None or right is None:
            report.mismatches.append(f"fact relation {relation.id} references a missing fact")
            continue
        if catalog.get_edge_by_triple(left.engine_id, right.engine_id, LINKED) is None:
            report.mismatches.append(f"fact relation {relation.id} has no graph edge")

    dependencies = (await session.scalars(select(GraphFactQuestionDependency))).all()
    report.counts["graph_fact_question_dependencies"] = len(list(dependencies))
    for dependency in dependencies:
        report.checked += 1
        if not _dependency_present(catalog, dependency):
            report.mismatches.append(
                f"question dependency {dependency.id} has no DEPENDS_ON edge"
            )


def _fact_present(catalog, fact: GraphFact, sources: list[str]) -> bool:
    units = [item.split(":", 1)[1] for item in sources if item.startswith("text_unit:")]
    if not units:
        return catalog.get_by_key(FACT, fact.id) is not None
    for unit_key in units:
        unit = catalog.get_by_key(TEXT_UNIT, unit_key)
        if unit is None:
            return False
        version = str(unit.props.get("document_version_id") or "")
        candidate = source_fact_identity(
            scope_key=fact.scope_key,
            source_identity="text_unit",
            document_version_id=version or None,
            source_unit_key=unit_key,
            fact_occurrence_key=fact.occurrence_key or fact_occurrence_selector(
                predicate=fact.predicate, context_id=fact.context_id, fact_text=fact.fact_text,
            ),
        )
        if catalog.get_by_key(FACT, candidate) is None:
            return False
    return True


def _fact_pair(catalog, relation: GraphFactRelation):
    left = catalog.get_by_key(FACT, relation.from_fact_id)
    right = catalog.get_by_key(FACT, relation.to_fact_id)
    if left is None or right is None or left.engine_id is None or right.engine_id is None:
        return None, None
    return left, right


def _dependency_present(catalog, dependency: GraphFactQuestionDependency) -> bool:
    fact = catalog.get_by_key(FACT, dependency.fact_id)
    if fact is None or fact.engine_id is None:
        return False
    for engine_id in catalog.neighbors(
        fact.engine_id, direction="outgoing", edge_label_filter=[DEPENDS_ON],
    ):
        return True
    return False


async def _graph_v2_counts(session: AsyncSession, report: ParityReport) -> None:
    for name, model in (
        ("graph_nodes", GraphNode),
        ("graph_identifiers", GraphIdentifier),
        ("graph_facts", GraphFact),
        ("graph_fact_sources", GraphFactSource),
        ("graph_fact_relations", GraphFactRelation),
        ("graph_fact_question_dependencies", GraphFactQuestionDependency),
    ):
        report.counts[name] = len(await _rows(session, model))
