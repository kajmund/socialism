"""Copy one fully migrated SQLite database into an empty PostgreSQL schema."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    Connection,
    Engine,
    MetaData,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)

from app.config import settings
from app.database import models as _models  # noqa: F401 — populate Base.metadata
from app.database.base import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_URL = "sqlite:///./data/opinionssimulator.db"
COPY_BATCH_SIZE = 500


def _sync_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


def _schema_revision(connection: Connection) -> str:
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" not in tables:
        raise RuntimeError("Database has no alembic_version table; run Alembic first")
    revisions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if len(revisions) != 1:
        raise RuntimeError(f"Expected one Alembic revision, found {revisions!r}")
    return revisions[0]


def _expected_revision() -> str:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head, found {heads!r}")
    return heads[0]


def _require_current_schema(connection: Connection, *, label: str) -> None:
    actual = _schema_revision(connection)
    expected = _expected_revision()
    if actual != expected:
        raise RuntimeError(
            f"{label} schema is at Alembic revision {actual}, expected {expected}"
        )


def _occupied_target_tables(
    connection: Connection, tables: Sequence[Table]
) -> list[str]:
    return [
        table.name
        for table in tables
        if connection.execute(select(func.count()).select_from(table)).scalar_one()
    ]


def _prepare_target(
    connection: Connection,
    tables: Sequence[Table],
    *,
    replace_target: bool,
) -> None:
    occupied = _occupied_target_tables(connection, tables)
    if not occupied:
        return
    if replace_target:
        if connection.dialect.name != "postgresql":
            for table in reversed(tables):
                connection.execute(table.delete())
            return
        quote = connection.dialect.identifier_preparer.quote
        table_names = ", ".join(quote(table.name) for table in tables)
        connection.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
        return
    if occupied:
        raise RuntimeError(
            "Target database contains migration-created or application rows. "
            "Use --replace-target only for the dedicated new target database: "
            + ", ".join(occupied)
        )


def _copy_table(source: Connection, target: Connection, table: Table) -> int:
    statement = select(table)
    primary_key = list(table.primary_key.columns)
    if primary_key:
        statement = statement.order_by(*primary_key)
    result = source.execute(statement)
    copied = 0
    while rows := result.mappings().fetchmany(COPY_BATCH_SIZE):
        target.execute(table.insert(), [dict(row) for row in rows])
        copied += len(rows)
    return copied


def _primary_key_values(connection: Connection, table: Table) -> set[tuple[object, ...]]:
    columns = list(table.primary_key.columns)
    if not columns:
        return set()
    return {tuple(row) for row in connection.execute(select(*columns))}


def _verify_table(source: Connection, target: Connection, table: Table) -> int:
    source_count = source.execute(select(func.count()).select_from(table)).scalar_one()
    target_count = target.execute(select(func.count()).select_from(table)).scalar_one()
    if source_count != target_count:
        raise RuntimeError(
            f"Row count mismatch for {table.name}: source={source_count}, target={target_count}"
        )
    if _primary_key_values(source, table) != _primary_key_values(target, table):
        raise RuntimeError(f"Primary-key mismatch for {table.name}")
    return source_count


def _reset_postgres_sequences(connection: Connection, tables: Sequence[Table]) -> None:
    if connection.dialect.name != "postgresql":
        return
    for table in tables:
        primary_key = list(table.primary_key.columns)
        if len(primary_key) != 1:
            continue
        column = primary_key[0]
        if not isinstance(column.type.python_type, type) or column.type.python_type is not int:
            continue
        maximum = connection.execute(select(func.max(column))).scalar_one()
        if maximum is None:
            continue
        connection.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:table_name, :column_name), "
                ":maximum, true)"
            ),
            {
                "table_name": table.name,
                "column_name": column.name,
                "maximum": maximum,
            },
        )


def copy_database(
    source_engine: Engine,
    target_engine: Engine,
    *,
    metadata: MetaData = Base.metadata,
    verify_revisions: bool = True,
    replace_target: bool = False,
) -> dict[str, int]:
    tables = list(metadata.sorted_tables)
    with source_engine.connect() as source, target_engine.begin() as target:
        if verify_revisions:
            _require_current_schema(source, label="Source")
            _require_current_schema(target, label="Target")
        source_tables = set(inspect(source).get_table_names())
        target_tables = set(inspect(target).get_table_names())
        missing_source = [table.name for table in tables if table.name not in source_tables]
        missing_target = [table.name for table in tables if table.name not in target_tables]
        if missing_source or missing_target:
            raise RuntimeError(
                f"Schema mismatch; missing source={missing_source}, missing target={missing_target}"
            )
        _prepare_target(target, tables, replace_target=replace_target)
        counts = {table.name: _copy_table(source, target, table) for table in tables}
        _reset_postgres_sequences(target, tables)
        for table in tables:
            _verify_table(source, target, table)
        return counts


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy a current SQLite database into an empty, migrated PostgreSQL database."
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE_URL, help="SQLite SQLAlchemy URL")
    parser.add_argument(
        "--target",
        default=settings.database_url,
        help="PostgreSQL SQLAlchemy URL (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--replace-target",
        action="store_true",
        help=(
            "Clear all application tables in the dedicated target before copying. "
            "Required when Alembic migrations created seed rows."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source_url = _sync_url(args.source)
    target_url = _sync_url(args.target)
    if not source_url.startswith("sqlite://"):
        raise RuntimeError("Source must be SQLite")
    if not target_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Target must use postgresql+psycopg://")
    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url, pool_pre_ping=True)
    try:
        counts = copy_database(
            source_engine,
            target_engine,
            replace_target=args.replace_target,
        )
    finally:
        source_engine.dispose()
        target_engine.dispose()
    total = sum(counts.values())
    print(f"Migrated and verified {total} rows across {len(counts)} tables.")


if __name__ == "__main__":
    main()
