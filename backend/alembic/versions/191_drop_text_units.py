"""Drop the SQL TextUnit mirror; OverGraph is the authoritative TextUnit store.

Revision ID: 191_drop_text_units
Revises: 190_drop_evidence_set_revalidations

All readers now load TextUnits from OverGraph (``load_domain_text_units`` /
``research.load_text_units``) and ingestion writes only the graph node, so the SQL
tables ``text_units`` and ``shared_text_chunks`` hold no authoritative data.

The cutover begins here: this revision runs the **fresh** SQL-vs-OverGraph parity
check for the graph mirror that revision 192 then drops. It runs before any DDL in
this transaction because the gate reads the database from a second connection: that
connection cannot see uncommitted tables and would block on the locks taken below.
An empty mirror (fresh database) has no SQL data to preserve, so it skips the gate.

Existing development databases may still carry TextUnit rows from the retired
dual-write. Such rows are copied to ``text_units_dropped`` /
``shared_text_chunks_dropped`` before the tables are dropped, and
``python -m app.services.knowledge.backfill_text_units`` can replay them into
OverGraph if a database predates the graph write.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "191_drop_text_units"
down_revision: str | Sequence[str] | None = "190_drop_evidence_set_revalidations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFERENCING = (
    ("document_knowledge_item_text_units", "text_unit_id"),
    ("knowledge_claim_text_units", "text_unit_id"),
)
# The twelve SQL knowledge-graph tables that revision 192 drops. Duplicated there on
# purpose: each migration records the schema it was written against.
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
_FK_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
_TEXT_UNIT_INDEXES = (
    ("ix_text_units_document_version_id", ["document_version_id"]),
    ("ix_text_units_document_id", ["document_id"]),
    ("ix_text_units_section_id", ["section_id"]),
    ("ix_text_units_document_ordinal", ["document_id", "ordinal"]),
    ("ix_text_units_version_ordinal", ["document_version_id", "ordinal"]),
    ("ix_text_units_content_hash", ["content_hash"]),
    ("ix_text_units_scope_type", ["scope_type"]),
    ("ix_text_units_scope_key", ["scope_key"]),
    ("ix_text_units_customer_id", ["customer_id"]),
)


def _async_url(url: sa.engine.URL) -> str:
    driver = url.drivername
    if driver.startswith("sqlite"):
        return url.set(drivername="sqlite+aiosqlite").render_as_string(hide_password=False)
    if driver in ("postgresql+psycopg", "postgresql+asyncpg"):
        return url.render_as_string(hide_password=False)
    if driver.startswith("postgresql"):
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    raise RuntimeError(f"unsupported database driver for the parity gate: {driver}")


def _graph_mirror_has_rows(connection) -> bool:
    inspector = sa.inspect(connection)
    return any(
        inspector.has_table(table)
        and connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in _GRAPH_TABLES
    )


def _require_parity(connection) -> None:
    if not _graph_mirror_has_rows(connection):
        return
    from app.services.knowledge.parity_gate import require_parity_sync

    require_parity_sync(_async_url(connection.engine.url))


def _preserve_rows(table: str, backup: str) -> int:
    """Keep pre-dual-write rows available for replay without blocking the upgrade."""
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
    if not rows:
        return 0
    exists = bind.execute(
        sa.text("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = :name")
        if bind.dialect.name == "sqlite"
        else sa.text("SELECT count(*) FROM information_schema.tables WHERE table_name = :name"),
        {"name": backup},
    ).scalar_one()
    if exists:
        bind.execute(sa.text(f"DROP TABLE {backup}"))
    bind.execute(sa.text(f"CREATE TABLE {backup} AS SELECT * FROM {table}"))
    return int(rows)


def _drop_text_unit_fk(table: str, column: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        rows = bind.execute(
            sa.text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:tbl AS regclass) AND contype = 'f'"
            ),
            {"tbl": table},
        ).all()
        for name, definition in rows:
            if "REFERENCES text_units" in definition:
                op.drop_constraint(name, table, type_="foreignkey")
        return
    with op.batch_alter_table(
        table, naming_convention=_FK_CONVENTION, recreate="always",
    ) as batch:
        batch.drop_constraint(f"fk_{table}_{column}_text_units", type_="foreignkey")


def _create_text_unit_fk(table: str, column: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Batch mode recreates the whole table, which re-renders constraints the
        # Postgres dialect cannot express; a direct ALTER is enough here.
        op.create_foreign_key(
            f"fk_{table}_{column}_text_units",
            table,
            "text_units",
            [column],
            ["id"],
            ondelete="CASCADE",
        )
        return
    with op.batch_alter_table(
        table, naming_convention=_FK_CONVENTION, recreate="always",
    ) as batch:
        batch.create_foreign_key(
            f"fk_{table}_{column}_text_units",
            "text_units",
            [column],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    _require_parity(op.get_bind())
    kept_units = _preserve_rows("text_units", "text_units_dropped")
    kept_chunks = _preserve_rows("shared_text_chunks", "shared_text_chunks_dropped")
    if kept_units:
        print(
            f"191_drop_text_units: kept {kept_units} TextUnit rows and {kept_chunks} chunk "
            "rows in *_dropped tables; replay with "
            "python -m app.services.knowledge.backfill_text_units"
        )
    for table, column in _REFERENCING:
        _drop_text_unit_fk(table, column)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS shared_text_chunks_immutable ON shared_text_chunks")
        op.execute("DROP TRIGGER IF EXISTS text_unit_content_immutable ON text_units")
        op.execute("DROP FUNCTION IF EXISTS reject_shared_chunk_update()")
    op.drop_table("text_units")
    op.drop_table("shared_text_chunks")


def downgrade() -> None:
    op.create_table(
        "shared_text_chunks",
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("content_hash"),
    )
    op.create_table(
        "text_units",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("locator", sa.String(length=128), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("embedding_id", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "(scope_type = 'shared' AND customer_id IS NULL AND scope_key = 'shared') OR "
            "(scope_type = 'customer' AND customer_id IS NOT NULL AND "
            "scope_key = 'customer:' || customer_id)",
            name="ck_text_units_knowledge_scope",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["canonical_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["document_sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["content_hash"], ["shared_text_chunks.content_hash"], ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for index, columns in _TEXT_UNIT_INDEXES:
        op.create_index(index, "text_units", columns)
    for table, column in _REFERENCING:
        _create_text_unit_fk(table, column)
