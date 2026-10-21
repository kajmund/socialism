"""Migrate existing facts to the additive, source-anchored identity contract.

Legacy facts used one identity per semantic fact and attached every matching source to it.
The additive contract needs one fact per source occurrence, so a legacy fact with several
source units is expanded into several facts. Relations are copied to every materialised fact
because they were stored on the merged fact.

Anything that cannot be derived from stored data is reported, never fabricated: the old
merge may have discarded which occurrence produced which wording.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact, GraphFactQuestionDependency, GraphFactRelation, GraphFactSource
from app.database.graph_v2 import GraphNode
from app.services.graph_v2.identity import (
    fact_occurrence_selector,
    source_fact_identity,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.labels import (
    CONTRADICTS,
    CONTEXT,
    DEPENDS_ON,
    FACT,
    OBJECT,
    SUBJECT,
    SUPPORTS,
    scope_label,
)
from app.services.overgraph.model import GraphRecord

FACT_EDGES = (SUBJECT, OBJECT, CONTEXT, SUPPORTS, CONTRADICTS, DEPENDS_ON)

NO_LOCATOR = {"episode", "answer", "question", "document"}


@dataclass
class FactMigrationReport:
    total: int = 0
    compliant: int = 0
    rewritten: int = 0
    kept_explicit_contract: int = 0
    materialised: int = 0
    unresolved: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return not self.unresolved

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "compliant": self.compliant,
            "rewritten": self.rewritten,
            "kept_explicit_contract": self.kept_explicit_contract,
            "materialised": self.materialised,
            "unresolved": list(self.unresolved),
        }


def _occurrence_key(fact: GraphFact) -> str:
    return fact.occurrence_key or fact_occurrence_selector(
        predicate=fact.predicate, context_id=fact.context_id, fact_text=fact.fact_text,
    )


async def migrate_fact_identities(session: AsyncSession) -> FactMigrationReport:
    report = FactMigrationReport()
    catalog = require_knowledge()
    facts = list((await session.scalars(select(GraphFact))).all())
    report.total = len(facts)
    for fact in facts:
        sources = list((await session.scalars(
            select(GraphFactSource).where(GraphFactSource.fact_id == fact.id)
        )).all())
        unit_keys = sorted({row.source_ref for row in sources if row.source_kind == "text_unit"})
        if not unit_keys:
            report.kept_explicit_contract += 1
            continue
        created = _materialise(catalog, fact, unit_keys, report)
        if created == 0:
            report.compliant += 1
        elif created == 1:
            report.rewritten += 1
        else:
            report.materialised += created
            report.rewritten += 1
    return report


def _materialise(catalog, fact: GraphFact, unit_keys: list[str], report) -> int:
    created = 0
    for unit_key in unit_keys:
        unit = catalog.get_by_key("TextUnit", unit_key)
        if unit is None:
            report.unresolved.append(f"{fact.id}: TextUnit {unit_key} is missing")
            continue
        version = str(unit.props.get("document_version_id") or "")
        if not version:
            report.unresolved.append(f"{fact.id}: TextUnit {unit_key} has no document version")
            continue
        new_key = source_fact_identity(
            scope_key=fact.scope_key,
            source_identity="text_unit",
            document_version_id=version,
            source_unit_key=unit_key,
            fact_occurrence_key=_occurrence_key(fact),
        )
        existing = catalog.get_by_key(FACT, new_key)
        if existing is not None:
            continue
        catalog.upsert_node(
            [FACT, scope_label(fact.scope_key)],
            new_key,
            props=_props(fact, unit_key, version),
        )
        node = catalog.get_by_key(FACT, new_key)
        if node is None or node.engine_id is None:
            raise RuntimeError(f"fact {new_key} was not written")
        _copy_edges(catalog, fact.id, node)
        created += 1
    return created


def _props(fact: GraphFact, unit_key: str, version: str) -> dict[str, object]:
    return {
        "scope_key": fact.scope_key,
        "predicate": fact.predicate,
        "fact_text": fact.fact_text,
        "normalized_text": fact.normalized_text,
        "occurrence_key": fact.occurrence_key,
        "source_key": fact.source_id,
        "target_key": fact.target_id,
        "context_key": fact.context_id or "",
        "status": fact.status,
        "created_at_ms": int(fact.created_at.timestamp() * 1000) if fact.created_at else 0,
        "valid_at_ms": int(fact.valid_at.timestamp() * 1000) if fact.valid_at else 0,
        "invalid_at_ms": 0,
        "attributes_json": json.dumps(fact.attributes, ensure_ascii=False, sort_keys=True),
        "identity_version": "source-fact-v1",
        "source_refs_json": json.dumps(
            [{"kind": "text_unit", "ref": unit_key}], ensure_ascii=False,
        ),
        "document_version_id": version,
        "migrated_from_fact": fact.id,
    }


def _copy_edges(catalog, old_key: str, node: GraphRecord) -> None:
    old = catalog.get_by_key(FACT, old_key)
    if old is None or old.engine_id is None:
        return
    for label in FACT_EDGES:
        for engine_id in catalog.neighbors(
            old.engine_id, direction="outgoing", edge_label_filter=[label],
        ):
            edge = catalog.get_edge_by_triple(old.engine_id, engine_id, label)
            if edge is None:
                continue
            catalog.upsert_edge(
                node.engine_id, engine_id, label,
                props=dict(edge.props), weight=edge.weight,
            )
        for engine_id in catalog.neighbors(
            old.engine_id, direction="incoming", edge_label_filter=[label],
        ):
            edge = catalog.get_edge_by_triple(engine_id, old.engine_id, label)
            if edge is None:
                continue
            catalog.upsert_edge(
                engine_id, node.engine_id, label,
                props=dict(edge.props), weight=edge.weight,
            )


async def unresolved_fact_ids(session: AsyncSession) -> list[str]:
    """Facts that reference endpoints or sources which are not resolvable any more."""
    catalog = require_knowledge()
    unresolved: list[str] = []
    for fact in (await session.scalars(select(GraphFact))).all():
        for endpoint in (fact.source_id, fact.target_id):
            if catalog.get_by_key("Entity", endpoint) is None:
                unresolved.append(f"{fact.id}: endpoint {endpoint} missing in graph")
    return unresolved


async def pending_dependencies(session: AsyncSession) -> int:
    rows = await session.scalars(select(GraphFactQuestionDependency))
    return len(list(rows.all()))


async def node_count(session: AsyncSession) -> int:
    return len(list((await session.scalars(select(GraphNode))).all()))


async def relation_count(session: AsyncSession) -> int:
    return len(list((await session.scalars(select(GraphFactRelation))).all()))
