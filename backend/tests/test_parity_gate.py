"""The destructive drop must require a fresh parity check, not an old fingerprint."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import KnowledgeClaimRecord, Kund
from app.services.knowledge.claims import KnowledgeClaim, knowledge_claim_id
from app.services.knowledge.parity_gate import GraphParityError, require_parity
from app.services.knowledge.persist import persist_extracted_knowledge


@pytest.fixture
async def database(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'parity.db'}"
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db, factory, url
    await engine.dispose()


async def _document_and_claim(session: AsyncSession) -> KnowledgeClaim:
    from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
    from tests.text_unit_fakes import persisted_text_unit

    session.add(CanonicalDocumentRecord(
        id="doc-p", customer_id=1, source_type="upload",
        canonical_uri="doc://p", title="P", extra={},
    ))
    session.add(DocumentVersionRecord(
        id="ver-p", document_id="doc-p", customer_id=1,
        content_hash="hash-p", mime_type="text/plain", extra={},
    ))
    await session.flush()
    await persisted_text_unit(
        session, id="tu-p", document_version_id="ver-p", document_id="doc-p",
        customer_id=1, section_id=None, ordinal=0, text="Nio månader gäller.",
    )
    claim = KnowledgeClaim(
        id=knowledge_claim_id(
            scope_key="customer:1", predicate="contract.termination_days",
            value={"days": 90},
        ),
        customer_id=1, predicate="contract.termination_days", value={"days": 90},
        supporting_text_unit_ids=("tu-p",),
    )
    await persist_extracted_knowledge(session, claims=[claim])
    await session.flush()
    return claim


async def test_gate_passes_when_the_graph_is_current(database, tmp_path, monkeypatch):
    from app.services.knowledge import parity_gate

    session, _factory, url = database
    await _document_and_claim(session)
    await session.commit()
    monkeypatch.setattr(parity_gate, "knowledge_catalog_directory", lambda: tmp_path / "graph")
    # Reuse the already open catalog directory of the test runtime instead of a fresh one.
    report = await parity_gate.require_parity(url)
    assert report["verified"] is True


async def test_gate_refuses_when_a_legacy_claim_is_missing_in_the_graph(database):
    session, _factory, url = database
    session.add(KnowledgeClaimRecord(
        id="legacy-gap", identity_key="legacy-gap", scope_key="customer:1",
        customer_id=1, scope_type="customer",
        predicate="contract.termination_days", value={"days": 90},
    ))
    await session.commit()
    with pytest.raises(GraphParityError, match="refusing to drop"):
        await require_parity(url)
