"""Parity verification before the SQL knowledge tables are dropped."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import KnowledgeClaimRecord, Kund
from app.services.knowledge.claims import KnowledgeClaim, knowledge_claim_id
from app.services.knowledge.persist import persist_extracted_knowledge
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.knowledge.verify_graph_parity import verify_parity


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


async def _document(session: AsyncSession, suffix: str) -> str:
    from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
    from tests.text_unit_fakes import persisted_text_unit

    session.add(CanonicalDocumentRecord(
        id=f"doc-{suffix}", customer_id=1, source_type="upload",
        canonical_uri=f"doc://{suffix}", title=suffix, extra={},
    ))
    session.add(DocumentVersionRecord(
        id=f"ver-{suffix}", document_id=f"doc-{suffix}", customer_id=1,
        content_hash=f"hash-{suffix}", mime_type="text/plain", extra={},
    ))
    await session.flush()
    unit_id = f"tu-{suffix}"
    await persisted_text_unit(
        session, id=unit_id, document_version_id=f"ver-{suffix}",
        document_id=f"doc-{suffix}", customer_id=1, section_id=None, ordinal=0,
        text=f"Passage {suffix} om uppsägningstiden.",
    )
    return unit_id


def _claim(units: tuple[str, ...]) -> KnowledgeClaim:
    return KnowledgeClaim(
        id=knowledge_claim_id(
            scope_key="customer:1", predicate="contract.termination_days",
            value={"days": 90},
        ),
        customer_id=1, predicate="contract.termination_days", value={"days": 90},
        supporting_text_unit_ids=units,
    )


async def test_parity_passes_for_a_claim_with_two_supports(session):
    first = await _document(session, "a")
    second = await _document(session, "b")
    claim = _claim((first, second))
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()
    report = await verify_parity(session)
    assert report.verified is True, report.mismatches
    assert report.fingerprint
    assert report.counts["claims_graph"] == 1


async def test_parity_reports_a_missing_graph_claim(session):
    unit_id = await _document(session, "c")
    claim = _claim((unit_id,))
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()
    # Legacy rows written before the mirror have no graph node.
    session.add(KnowledgeClaimRecord(
        id="legacy-only", identity_key="legacy-only", scope_key="customer:1",
        customer_id=1, scope_type="customer",
        predicate="contract.termination_days", value={"days": 90},
    ))
    await session.flush()
    report = await verify_parity(session)
    assert report.verified is False
    assert any("legacy-only" in item for item in report.mismatches)


async def test_parity_covers_graph_v2_tables_before_the_drop(session):
    """Occurrence-level checks: legacy facts must exist in the graph per source unit."""
    from app.database.graph_v2 import GraphFact, GraphFactSource
    from app.services.graph_v2.types import NodeInput
    from app.services.knowledge.migrate_fact_identity import migrate_fact_identities
    from app.services.overgraph.write import upsert_entity

    unit_id = await _document(session, "gv2")
    graph = require_knowledge()
    scope = customer_scope(1)
    source_id = upsert_entity(graph, NodeInput(
        node_type="legal.source", name="Lagen", scope=scope,
    )).key
    target_id = upsert_entity(graph, NodeInput(
        node_type="legal.issue", name="Frågan", scope=scope,
    )).key
    session.add(GraphFact(
        id="legacy-fact", identity_key="legacy-fact", scope_key="customer:1",
        customer_id=1, source_id=source_id, target_id=target_id,
        predicate="legal.rule", fact_text="Regeln gäller.",
        normalized_text="regeln gäller.", occurrence_key="", status="active", attributes={},
    ))
    await session.flush()
    session.add(GraphFactSource(
        fact_id="legacy-fact", source_kind="text_unit", source_ref=unit_id,
    ))
    await session.flush()

    before = await verify_parity(session)
    assert before.verified is False
    assert any("legacy-fact" in item for item in before.mismatches)

    await migrate_fact_identities(session)
    after = await verify_parity(session)
    assert after.verified is True, after.mismatches
    assert after.counts["graph_facts"] == 1
