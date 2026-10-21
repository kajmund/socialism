"""Backfill of legacy SQL claims into OverGraph.

Legacy rows are materialised under their SQL id, and the backfill verifies that the graph
reports exactly the same supporting TextUnits before the SQL tables can be dropped.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    Kund,
)
from app.services.knowledge.backfill_claims import backfill_claims
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import (
    claim_in_graph,
    supporting_text_units,
)
from tests.text_unit_fakes import persisted_text_unit


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


async def _legacy_claim(session: AsyncSession) -> tuple[str, list[str]]:
    """A claim written before the graph mirror: SQL row plus TextUnit links only."""
    from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord

    session.add(CanonicalDocumentRecord(
        id="doc-l", customer_id=1, source_type="upload",
        canonical_uri="doc://l", title="L", extra={},
    ))
    session.add(DocumentVersionRecord(
        id="ver-l", document_id="doc-l", customer_id=1,
        content_hash="hash-l", mime_type="text/plain", extra={},
    ))
    await session.flush()
    units = []
    for ordinal, unit_id in enumerate(("tu-one", "tu-two")):
        await persisted_text_unit(
            session, id=unit_id, document_version_id="ver-l", document_id="doc-l",
            customer_id=1, section_id=None, ordinal=ordinal,
            text=f"Passage {ordinal} about the notice period.",
        )
        units.append(unit_id)
    from app.services.knowledge.identity import knowledge_claim_identity

    identity = knowledge_claim_identity(
        scope_key="customer:1", predicate="contract.termination_days", value={"days": 90},
    )
    session.add(KnowledgeClaimRecord(
        id="legacy-claim",
        identity_key=identity,
        scope_key="customer:1",
        customer_id=1,
        scope_type="customer",
        predicate="contract.termination_days",
        value={"days": 90},
    ))
    await session.flush()
    for ordinal, unit_id in enumerate(units):
        session.add(KnowledgeClaimTextUnit(
            claim_id="legacy-claim", text_unit_id=unit_id, ordinal=ordinal,
            relation="SUPPORTED_BY",
        ))
    await session.flush()
    return "legacy-claim", units


async def test_backfill_materialises_a_legacy_claim_under_its_sql_id(session):
    claim_id, units = await _legacy_claim(session)
    report = await backfill_claims(session)

    assert report.rows == 1
    assert report.mirrored == 1
    assert report.verified == 1
    assert report.mismatches == []
    assert report.verified_completely is True

    catalog = require_knowledge()
    node = claim_in_graph(catalog, scope_key="customer:1", identity=claim_id)
    assert node is not None
    assert sorted(supporting_text_units(catalog, claim_id)) == sorted(units)


async def test_backfill_is_idempotent(session):
    claim_id, units = await _legacy_claim(session)
    await backfill_claims(session)
    second = await backfill_claims(session)
    assert second.verified_completely is True
    assert sorted(supporting_text_units(require_knowledge(), claim_id)) == sorted(units)


async def test_backfill_reports_a_support_mismatch(session):
    """Divergence between the graph and the legacy links must be reported, not hidden."""
    claim_id, units = await _legacy_claim(session)
    await backfill_claims(session)
    from sqlalchemy import delete

    await session.execute(
        delete(KnowledgeClaimTextUnit).where(
            KnowledgeClaimTextUnit.claim_id == claim_id,
            KnowledgeClaimTextUnit.text_unit_id == units[0],
        )
    )
    await session.flush()
    report = await backfill_claims(session)
    assert report.verified_completely is False
    assert report.mismatches
    assert "support mismatch" in report.mismatches[0]


async def test_rekey_merges_legacy_duplicates_in_the_graph_too(session):
    """Pre-126 duplicates are merged in SQL; the graph must not keep both nodes."""
    from sqlalchemy import select

    from app.database.models import KnowledgeClaimRecord, KnowledgeClaimTextUnit
    from app.services.knowledge.claim_rekey import backfill_source_independent_claims
    from app.services.knowledge.graph_audit import graph_audit_counts
    from app.services.overgraph.legal_claims import supporting_text_units

    _claim_id, units = await _legacy_claim(session)
    session.add(KnowledgeClaimRecord(
        id="legacy-dup", identity_key="pre-126-identity", scope_key="customer:1",
        customer_id=1, scope_type="customer",
        predicate="contract.termination_days", value={"days": 90},
    ))
    await session.flush()
    session.add(KnowledgeClaimTextUnit(
        claim_id="legacy-dup", text_unit_id=units[1], ordinal=0, relation="SUPPORTED_BY",
    ))
    await session.flush()
    await backfill_claims(session)

    await backfill_source_independent_claims(session)
    winner = (await session.execute(select(KnowledgeClaimRecord))).scalar_one()
    catalog = require_knowledge()
    assert graph_audit_counts(catalog)["claims"] == 1
    assert sorted(supporting_text_units(catalog, winner.id)) == sorted(units)
    assert catalog.get_by_key("Claim", "legacy-dup") is None
