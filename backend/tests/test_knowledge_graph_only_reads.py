"""Knowledge claim scope/supersession must not read the dropped SQL claim tables."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.claims import (
    KnowledgeClaim,
    knowledge_claim_id,
    persist_knowledge_claim,
    supersede_knowledge_claim,
)
from app.services.knowledge.relationships import _endpoint_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import claim_is_superseded
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


async def _seed_claim(db: Path) -> KnowledgeClaim:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(
            CanonicalDocumentRecord(
                id="doc-a", customer_id=1, source_type="upload",
                canonical_uri="doc://graph-only", title="A", extra={},
            )
        )
        session.add(
            DocumentVersionRecord(
                id="ver-a", document_id="doc-a", customer_id=1,
                content_hash="hash", mime_type="text/plain", extra={},
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
        value = {"value": False}
        claim = KnowledgeClaim(
            id=knowledge_claim_id(
                scope_key="customer:1", predicate="outcome.granted", value=value
            ),
            customer_id=1,
            predicate="outcome.granted",
            value=value,
            supporting_text_unit_ids=("tu-hold",),
        )
        await persist_knowledge_claim(session, claim)
        await session.commit()
    await engine.dispose()
    return claim


@pytest.mark.asyncio
async def test_endpoint_scope_for_claim_reads_the_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _migrated_head_db(tmp_path, monkeypatch)
    claim = await _seed_claim(db)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            scope = await _endpoint_scope(session, "claim", claim.id)
            assert scope is not None
            assert scope.customer_id == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_entity_endpoint_scope_does_not_read_dropped_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _migrated_head_db(tmp_path, monkeypatch)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            scope = await _endpoint_scope(session, "entity", "missing-entity-id")
            assert scope is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_supersede_claim_reads_the_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _migrated_head_db(tmp_path, monkeypatch)
    claim = await _seed_claim(db)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            assert claim_is_superseded(require_knowledge(), claim.id) is False
            closed = await supersede_knowledge_claim(session, claim.id)
            assert closed.id == claim.id
            assert claim_is_superseded(require_knowledge(), claim.id) is True
            await session.commit()
    finally:
        await engine.dispose()
