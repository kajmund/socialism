"""Existing canonical sources gain explicit natures without changing identity."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.fixture
def migration_db(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/141_canonical_evidence_nature.py"
    spec = importlib.util.spec_from_file_location("evidence_nature_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    table = sa.Table(
        "canonical_documents",
        sa.MetaData(),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_type", sa.String()),
        sa.Column("canonical_uri", sa.String()),
        sa.Column("extra", sa.JSON()),
    )
    table.metadata.create_all(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        yield migration, connection, table
    engine.dispose()


@pytest.mark.parametrize(
    "path,nature",
    [
        ("1915:218", "swedish_law"),
        ("dom/nja/2021s943", "swedish_case_law"),
        ("dom/ad/2003:1", "swedish_case_law"),
        ("prop/1975/76:81", "swedish_preparatory_works"),
        ("sou/1974:83", "swedish_preparatory_works"),
        ("ds/2012:31", "swedish_preparatory_works"),
        ("bet/1975/76:LU21", "swedish_preparatory_works"),
        ("rskr/1975/76:100", "swedish_preparatory_works"),
    ],
)
def test_backfill_preserves_identity_and_context(migration_db, path, nature):
    migration, connection, table = migration_db
    extra = {"provider": "lagen_nu", "knowledge_case_id": "case-1", "module": "dd"}
    connection.execute(
        table.insert(),
        {
            "id": "canonical-id",
            "source_type": "lagen_nu",
            "canonical_uri": f"https://lagen.nu/{path}",
            "extra": extra,
        },
    )
    migration.upgrade()
    migration.upgrade()
    row = connection.execute(sa.select(table)).mappings().one()
    assert row["id"] == "canonical-id"
    assert row["source_type"] == "lagen_nu"
    assert row["extra"] == {**extra, "evidence_nature": nature}
    migration.downgrade()
    assert connection.scalar(sa.select(table.c.extra)) == extra


@pytest.mark.parametrize("uri", ["https://lagen.nu/unknown/a", "https://foreign.test/1915:218"])
def test_unknown_namespace_aborts_before_any_update(migration_db, uri):
    migration, connection, table = migration_db
    connection.execute(
        table.insert(),
        [
            {
                "id": "known",
                "source_type": "lagen_nu",
                "canonical_uri": "https://lagen.nu/1915:218",
                "extra": {},
            },
            {"id": "unknown", "source_type": "lagen_nu", "canonical_uri": uri, "extra": {}},
        ],
    )
    with pytest.raises(ValueError, match="lagen.nu document"):
        migration.upgrade()
    assert list(connection.scalars(sa.select(table.c.extra))) == [{}, {}]


def test_conflicting_declaration_is_rejected_and_other_providers_are_untouched(migration_db):
    migration, connection, table = migration_db
    extra = {"evidence_nature": "swedish_case_law"}
    connection.execute(
        table.insert(),
        {
            "id": "law",
            "source_type": "lagen_nu",
            "canonical_uri": "https://lagen.nu/1915:218",
            "extra": extra,
        },
    )
    with pytest.raises(ValueError, match="Conflicting"):
        migration.upgrade()
    connection.execute(table.update().values(source_type="uploaded_file"))
    migration.upgrade()
    migration.downgrade()
    assert connection.scalar(sa.select(table.c.extra)) == extra
