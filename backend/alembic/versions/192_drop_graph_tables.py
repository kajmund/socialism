"""Drop the SQL graph mirror; OverGraph is the authoritative knowledge graph.

Revision ID: 192_drop_graph_tables
Revises: 191_drop_text_units

Every writer now targets OverGraph and every reader loads from it, so the twelve SQL graph
tables hold no authoritative data.

The drop is destructive, so revision 191 runs a **fresh** SQL-vs-OverGraph parity check
(``knowledge/parity_gate.py``) at the start of the cutover transaction, before any DDL.
A previously approved fingerprint is not accepted: the database or catalog may have
changed since. An empty mirror (fresh database) has no SQL data to preserve, so it skips
the gate and only drops the empty tables.

Rows are also copied to ``<table>_dropped`` before the tables are dropped, so development
data is never silently lost; if a database predates the graph write, run
``python -m app.services.knowledge.backfill_claims`` and the fact migration first.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "192_drop_graph_tables"
down_revision: str | Sequence[str] | None = "191_drop_text_units"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRAPH_TABLES = (
    "graph_fact_question_dependencies",
    "graph_fact_relations",
    "graph_fact_sources",
    "graph_facts",
    "graph_identifiers",
    "graph_nodes",
    "knowledge_claim_answers",
    "knowledge_claim_text_units",
    "knowledge_claims",
    "knowledge_relationships",
    "knowledge_entities",
    "knowledge_observations",
)
# Children first so foreign keys never block the drop.
_DROP_ORDER = _GRAPH_TABLES


def _existing(connection, table: str) -> bool:
    return sa.inspect(connection).has_table(table)


def _referencing_foreign_keys(connection, tables: list[str]) -> list[tuple[str, str]]:
    """Foreign keys on retained tables that point at a table that is about to be dropped."""
    if connection.dialect.name != "postgresql":
        return []
    rows = connection.execute(
        sa.text(
            "SELECT c.conrelid::regclass::text, c.conname "
            "FROM pg_constraint c "
            "JOIN pg_class target ON target.oid = c.confrelid "
            "WHERE c.contype = 'f' AND target.relname IN :names"
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"names": tables},
    ).all()
    return [(str(table), str(name)) for table, name in rows]


def _restore_foreign_keys(connection) -> None:
    """Re-add constraints between retained and recreated tables after a downgrade.

    The dropped tables are recreated without their foreign keys because some referenced
    tables (``text_units``) are recreated by revision 191's downgrade, which runs later.
    """
    from app.database.base import Base

    inspector = sa.inspect(connection)
    present = set(inspector.get_table_names())
    existing = {
        fk["name"]
        for table in present
        for fk in inspector.get_foreign_keys(table)
        if fk.get("name")
    }
    for table in Base.metadata.sorted_tables:
        if table.name not in present:
            continue
        for constraint in table.constraints:
            if not isinstance(constraint, sa.ForeignKeyConstraint):
                continue
            # Unnamed constraints only exist inline in CREATE TABLE; they are either
            # recreated with the table or not managed by this migration.
            if constraint.name is None or constraint.name in existing:
                continue
            if not all(element.column.table.name in present for element in constraint.elements):
                continue
            columns = ", ".join(f'"{element.parent.name}"' for element in constraint.elements)
            target = next(iter(constraint.elements)).column.table.name
            target_columns = ", ".join(f'"{element.column.name}"' for element in constraint.elements)
            ondelete = f" ON DELETE {constraint.ondelete}" if constraint.ondelete else ""
            connection.execute(sa.text(
                f'ALTER TABLE "{table.name}" ADD CONSTRAINT "{constraint.name}" '
                f'FOREIGN KEY ({columns}) REFERENCES "{target}" ({target_columns}){ondelete}'
            ))


def upgrade() -> None:
    connection = op.get_bind()
    present = [table for table in _GRAPH_TABLES if _existing(connection, table)]
    if not present:
        return
    # The fresh parity check ran at the start of revision 191, before this transaction
    # touched the schema; a second connection could neither see nor lock against these
    # tables from inside it.
    for table, constraint in _referencing_foreign_keys(connection, present):
        connection.execute(sa.text(f'ALTER TABLE {table} DROP CONSTRAINT "{constraint}"'))
    for table in present:
        backup = f"{table}_dropped"
        if not _existing(connection, backup):
            connection.execute(sa.text(
                f"CREATE TABLE {backup} AS SELECT * FROM {table}"
            ))
    for table in _DROP_ORDER:
        if _existing(connection, table):
            op.drop_table(table)


def downgrade() -> None:
    from sqlalchemy.schema import CreateTable

    from app.database.base import Base

    connection = op.get_bind()
    for table in reversed(_DROP_ORDER):
        if table not in Base.metadata.tables:
            continue
        if not _existing(connection, table):
            connection.execute(CreateTable(
                Base.metadata.tables[table], include_foreign_key_constraints=[],
            ))
    _restore_foreign_keys(connection)
    inspector = sa.inspect(connection)
    for table in reversed(_DROP_ORDER):
        backup = f"{table}_dropped"
        if not inspector.has_table(backup) or not inspector.has_table(table):
            continue
        columns = [column["name"] for column in inspector.get_columns(table)]
        column_list = ", ".join(columns)
        connection.execute(sa.text(
            f"INSERT INTO {table} ({column_list}) "
            f"SELECT {column_list} FROM {backup}"
        ))
