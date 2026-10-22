"""Claim writeback must work on the Alembic-migrated schema, not only create_all."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.claim_store import persist_domain_claim
from app.services.knowledge.claims import KnowledgeClaim, knowledge_claim_id
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import claim_in_graph
from tests.text_unit_fakes import persisted_text_unit


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
    return db


async def _claim(db: Path) -> KnowledgeClaim:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(
            CanonicalDocumentRecord(
                id="doc-a",
                customer_id=1,
                source_type="upload",
                canonical_uri="doc://head",
                title="A",
                extra={},
            )
        )
        session.add(
            DocumentVersionRecord(
                id="ver-a",
                document_id="doc-a",
                customer_id=1,
                content_hash="hash",
                mime_type="text/plain",
                extra={},
            )
        )
        await persisted_text_unit(
            session,
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=0,
            text="The court held that the clause was not adjusted.",
        )
        await session.flush()
    await engine.dispose()
    value = {"value": False}
    return KnowledgeClaim(
        id=knowledge_claim_id(
            scope_key="customer:1", predicate="outcome.granted", value=value
        ),
        customer_id=1,
        predicate="outcome.granted",
        value=value,
        supporting_text_unit_ids=("tu-hold",),
    )


@pytest.mark.asyncio
async def test_claim_writeback_works_after_head_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _migrated_head_db(tmp_path, monkeypatch)
    claim = await _claim(db)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            first, reused = await persist_domain_claim(session, claim)
            assert reused is False
            assert first.id == claim.id
            assert (
                claim_in_graph(
                    require_knowledge(), scope_key="customer:1", identity=claim.id
                )
                is not None
            )
            second, reused_again = await persist_domain_claim(session, claim)
            assert reused_again is True
            assert second.id == claim.id
            await session.commit()
    finally:
        await engine.dispose()
