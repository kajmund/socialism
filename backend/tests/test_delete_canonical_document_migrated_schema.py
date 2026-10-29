"""Document delete must not read SQL claim tables dropped in migration 192."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.claims import KnowledgeClaim, knowledge_claim_id
from app.services.knowledge.persistence import delete_canonical_document
from app.services.knowledge.persist import persist_extracted_knowledge
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import evidence_links, legal_claim_key
from tests.text_unit_fakes import persisted_text_unit

_VALUE = {"value": False}
_PREDICATE = "outcome.granted"


def _migrated_head_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "head.sqlite"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    with sqlite3.connect(db) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert "knowledge_claims" not in names
    assert "knowledge_claim_text_units" not in names
    return db


async def _seed_document(session: AsyncSession, suffix: str) -> str:
    session.add(
        CanonicalDocumentRecord(
            id=f"doc-{suffix}",
            customer_id=1,
            source_type="upload",
            canonical_uri=f"doc://{suffix}",
            title=suffix,
            extra={},
        )
    )
    version_id = f"ver-{suffix}"
    session.add(
        DocumentVersionRecord(
            id=version_id,
            document_id=f"doc-{suffix}",
            customer_id=1,
            content_hash=f"hash-{suffix}",
            mime_type="text/plain",
            extra={},
        )
    )
    await session.flush()
    await persisted_text_unit(
        session,
        id=f"tu-{suffix}",
        document_version_id=version_id,
        document_id=f"doc-{suffix}",
        customer_id=1,
        section_id=None,
        ordinal=0,
        text=f"The court held that the clause was not adjusted ({suffix}).",
    )
    return f"tu-{suffix}"


def _claim(unit_id: str) -> KnowledgeClaim:
    return KnowledgeClaim(
        id=knowledge_claim_id(scope_key="customer:1", predicate=_PREDICATE, value=_VALUE),
        customer_id=1,
        predicate=_PREDICATE,
        value=_VALUE,
        supporting_text_unit_ids=(unit_id,),
    )


async def test_delete_canonical_document_on_migrated_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _migrated_head_db(tmp_path, monkeypatch)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        first = await _seed_document(session, "a")
        second = await _seed_document(session, "b")
        claim = _claim(first)
        await persist_extracted_knowledge(session, claims=[claim])
        await persist_extracted_knowledge(session, claims=[_claim(second)])
        await session.flush()

        catalog = require_knowledge()
        key = legal_claim_key(claim.scope, claim.predicate, claim.value)
        assert len(evidence_links(catalog, key)) == 2

        await delete_canonical_document(session, "doc-a")
        await session.flush()

        remaining = [
            str(link.props["document_version_id"]) for link in evidence_links(catalog, key)
        ]
        assert remaining == ["ver-b"]
        assert catalog.get_by_key("Claim", key) is not None
    await engine.dispose()
