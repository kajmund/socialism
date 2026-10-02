"""Shared text migration preserves occurrence IDs and all incoming references."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.services.knowledge.units import hash_text


@pytest.fixture
def migration_db(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/e8c2f4a1b6d0_shared_text_chunks.py"
    spec = importlib.util.spec_from_file_location("shared_chunk_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("""CREATE TABLE text_units (
            id VARCHAR(64) PRIMARY KEY, text TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL,
            document_version_id TEXT NOT NULL, locator TEXT, scope_key TEXT, valid_to TEXT
        )"""))
        connection.execute(sa.text("""CREATE TABLE support (
            id INTEGER PRIMARY KEY, unit_id TEXT REFERENCES text_units(id) ON DELETE CASCADE
        )"""))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        yield migration, connection
    engine.dispose()


def seed(connection, *, bad_hash=False):
    content = "Åäö. Exakt  text."
    connection.execute(sa.text("""INSERT INTO text_units
        (id,text,content_hash,document_version_id,locator,scope_key,valid_to)
        VALUES (:id,:text,:hash,:version,:locator,:scope,:valid_to)"""), [
        {"id": "a", "text": content, "hash": hash_text(content), "version": "version-a",
         "locator": "P36", "scope": "customer:1", "valid_to": "2025-01-01"},
        {"id": "b", "text": content, "hash": "wrong" if bad_hash else hash_text(content),
         "version": "version-b", "locator": "P37", "scope": "customer:2", "valid_to": None},
    ])
    connection.execute(sa.text("INSERT INTO support VALUES (1,'a'),(2,'b')"))


def test_upgrade_and_downgrade_preserve_text_ids_history_and_references(migration_db):
    migration, connection = migration_db
    seed(connection)
    before = connection.execute(sa.text("SELECT * FROM text_units ORDER BY id")).mappings().all()
    migration.upgrade()
    assert "text" not in {col["name"] for col in sa.inspect(connection).get_columns("text_units")}
    assert connection.scalar(sa.text("SELECT count(*) FROM shared_text_chunks")) == 1
    assert connection.execute(sa.text("SELECT * FROM support ORDER BY id")).all() == [(1,"a"),(2,"b")]
    joined = connection.execute(sa.text("""SELECT u.id, c.text, u.content_hash,
        u.document_version_id, u.locator, u.scope_key, u.valid_to FROM text_units u
        JOIN shared_text_chunks c USING(content_hash) ORDER BY u.id""")).mappings().all()
    assert [dict(row) for row in joined] == [dict(row) for row in before]
    assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
    migration.downgrade()
    after = connection.execute(sa.text("SELECT * FROM text_units ORDER BY id")).mappings().all()
    assert [dict(row) for row in after] == [dict(row) for row in before]
    assert connection.scalar(sa.text("SELECT count(*) FROM support")) == 2


def test_bad_stored_sha_aborts_before_any_schema_change(migration_db):
    migration, connection = migration_db
    seed(connection, bad_hash=True)
    with pytest.raises(ValueError, match="TextUnit b SHA"):
        migration.upgrade()
    assert "shared_text_chunks" not in sa.inspect(connection).get_table_names()
    assert connection.scalar(sa.text("SELECT count(*) FROM support")) == 2
    assert "text" in {col["name"] for col in sa.inspect(connection).get_columns("text_units")}


def test_shared_text_cannot_be_overwritten_after_migration(migration_db):
    migration, connection = migration_db
    seed(connection)
    migration.upgrade()
    with pytest.raises(sa.exc.IntegrityError, match="immutable"):
        connection.execute(sa.text("UPDATE shared_text_chunks SET text='changed'"))
    assert connection.scalar(sa.text("SELECT text FROM shared_text_chunks")) == "Åäö. Exakt  text."


def test_sqlite_fk_enabled_is_rejected_before_destructive_batch(migration_db):
    migration, connection = migration_db
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    with pytest.raises(RuntimeError, match="foreign_keys=OFF"):
        migration.upgrade()
    assert "shared_text_chunks" not in sa.inspect(connection).get_table_names()
