"""Backfill replay must prove content hashes and OverGraph read-back before dropping."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.knowledge import backfill_text_units as backfill
from app.services.knowledge.units import hash_text
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.text_units import load_domain_text_unit

TEXT = "Paragraf 12 reglerar uppsägning."
HASH = hash_text(TEXT)


def _create_backup(connection: sa.Connection) -> None:
    connection.execute(sa.text(
        "CREATE TABLE shared_text_chunks_dropped (content_hash VARCHAR(64) PRIMARY KEY, text TEXT)"
    ))
    connection.execute(sa.text(
        "CREATE TABLE text_units_dropped ("
        "id VARCHAR(64), scope_type VARCHAR(16), scope_key VARCHAR(64), customer_id INTEGER, "
        "document_id VARCHAR(64), document_version_id VARCHAR(64), section_id VARCHAR(64), "
        "ordinal INTEGER, content_hash VARCHAR(64), locator VARCHAR(128), page_start INTEGER, "
        "page_end INTEGER, char_start INTEGER, char_end INTEGER, valid_from, valid_to, extra)"
    ))


def _seed(connection: sa.Connection, *, unit_id: str = "unit-1", text: str = TEXT,
          stored_hash: str | None = None) -> None:
    connection.execute(
        sa.text("INSERT INTO shared_text_chunks_dropped VALUES (:hash, :text)"),
        {"hash": hash_text(text), "text": text},
    )
    connection.execute(
        sa.text(
            "INSERT INTO text_units_dropped VALUES (:id, 'customer', 'customer:1', 1, 'doc-1', "
            "'ver-1', NULL, 0, :hash, 'p1', NULL, NULL, 0, 11, NULL, NULL, '{}')"
        ),
        {"id": unit_id, "hash": stored_hash or hash_text(text)},
    )


@pytest.fixture
def catalog(tmp_path):
    opened = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=8)
    try:
        yield opened
    finally:
        opened.close()


def test_replay_verifies_content_hash_and_overgraph_readback(tmp_path, catalog):
    db = tmp_path / "backup.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        _create_backup(connection)
        _seed(connection)
        rows = backfill.load_rows(connection)

    report = backfill.replay(rows, catalog)

    assert report.rows == 1
    assert report.replayed == 1
    assert report.verified == 1
    assert report.mismatches == []
    assert report.verified_completely is True
    replayed = load_domain_text_unit(catalog, unit_id="unit-1")
    assert replayed is not None
    assert (replayed.text, replayed.content_hash) == (TEXT, HASH)
    assert replayed.document_version_id == "ver-1"


def test_replay_reports_hash_mismatch_and_keeps_backup(tmp_path, catalog):
    db = tmp_path / "corrupt.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        _create_backup(connection)
        _seed(connection, stored_hash="b" * 64)
        rows = backfill.load_rows(connection)

    report = backfill.replay(rows, catalog)

    assert report.replayed == 0
    assert report.verified == 0
    assert report.verified_completely is False
    assert any("content_hash does not match stored text" in item for item in report.mismatches)
    assert load_domain_text_unit(catalog, unit_id="unit-1") is None


def test_replay_reports_missing_chunk_text(tmp_path, catalog):
    db = tmp_path / "orphan.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        _create_backup(connection)
        connection.execute(sa.text(
            "INSERT INTO text_units_dropped VALUES ('unit-orphan', 'customer', 'customer:1', 1, "
            "'doc-1', 'ver-1', NULL, 0, :hash, 'p1', NULL, NULL, 0, 11, NULL, NULL, '{}')"
        ), {"hash": HASH})
        rows = backfill.load_rows(connection)

    report = backfill.replay(rows, catalog)

    assert report.verified_completely is False
    assert report.mismatches == ["unit-orphan: content_hash does not match stored text"]


async def test_drop_backup_is_refused_until_every_row_is_verified(tmp_path, monkeypatch):
    db = tmp_path / "refuse.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as connection:
        await connection.run_sync(_create_backup)
        await connection.run_sync(lambda sync: _seed(sync, stored_hash="c" * 64))
    monkeypatch.setattr(backfill, "engine", engine)
    monkeypatch.setattr(
        backfill, "open_catalog",
        lambda *args, **kwargs: open_catalog(tmp_path / "k1", kind="knowledge", dimension=8),
    )
    try:
        with pytest.raises(RuntimeError, match="Refusing --drop-backup"):
            await backfill.backfill(drop_backup_flag=True)
        async with engine.begin() as connection:
            assert await connection.run_sync(backfill.backup_exists) is True
    finally:
        await engine.dispose()


async def test_drop_backup_removes_tables_only_after_verified_replay(tmp_path, monkeypatch):
    db = tmp_path / "verified.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as connection:
        await connection.run_sync(_create_backup)
        await connection.run_sync(_seed)
    monkeypatch.setattr(backfill, "engine", engine)
    monkeypatch.setattr(
        backfill, "open_catalog",
        lambda *args, **kwargs: open_catalog(tmp_path / "k2", kind="knowledge", dimension=8),
    )
    try:
        result = await backfill.backfill(drop_backup_flag=True)
        assert result["verified_completely"] is True
        assert result["dropped_backup_rows"] == 2
        async with engine.begin() as connection:
            assert await connection.run_sync(backfill.backup_exists) is False
        reopened = open_catalog(tmp_path / "k2", kind="knowledge", dimension=8)
        try:
            assert load_domain_text_unit(reopened, unit_id="unit-1") is not None
        finally:
            reopened.close()
    finally:
        await engine.dispose()


def test_fingerprint_is_bound_to_catalog_path_database_and_rows(tmp_path):
    first = open_catalog(tmp_path / "a", kind="knowledge", dimension=8)
    second = open_catalog(tmp_path / "b", kind="knowledge", dimension=8)
    rows = [{"id": "u1", "content_hash": "a" * 64}]
    changed = [{"id": "u1", "content_hash": "b" * 64}]
    try:
        base = backfill.fingerprint(rows, first, "db")
        assert base == backfill.fingerprint(rows, first, "db")
        assert base != backfill.fingerprint(rows, second, "db")
        assert base != backfill.fingerprint(rows, first, "other-db")
        assert base != backfill.fingerprint(changed, first, "db")
    finally:
        first.close()
        second.close()


async def test_stale_fingerprint_keeps_backup_and_fresh_one_allows_drop(
    tmp_path, monkeypatch,
):
    db = tmp_path / "fingerprint.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as connection:
        await connection.run_sync(_create_backup)
        await connection.run_sync(_seed)
    monkeypatch.setattr(backfill, "engine", engine)
    monkeypatch.setattr(
        backfill, "open_catalog",
        lambda *args, **kwargs: open_catalog(tmp_path / "k3", kind="knowledge", dimension=8),
    )
    try:
        verified = await backfill.backfill(drop_backup_flag=False)
        assert verified["verified_completely"] is True
        assert verified["fingerprint"]
        assert verified["catalog"].endswith("k3")
        assert "fingerprint.db" in verified["database"]
        with pytest.raises(RuntimeError, match="fingerprint does not match"):
            await backfill.backfill(drop_backup_flag=True, expect_fingerprint="0" * 64)
        async with engine.begin() as connection:
            assert await connection.run_sync(backfill.backup_exists) is True
        dropped = await backfill.backfill(
            drop_backup_flag=True, expect_fingerprint=verified["fingerprint"],
        )
        assert dropped["dropped_backup_rows"] == 2
        async with engine.begin() as connection:
            assert await connection.run_sync(backfill.backup_exists) is False
    finally:
        await engine.dispose()
