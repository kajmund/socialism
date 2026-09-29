"""Durable Graph v2 projection after research writeback.

Revision ID: 128_graph_ingest_outbox
Revises: 127_graph_v2
"""

import sqlalchemy as sa
from alembic import op

revision = "128_graph_ingest_outbox"
down_revision = "127_graph_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_ingest_work",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("kunder.id"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_graph_ingest_pending", "graph_ingest_work", ["status", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE graph_ingest_work ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("graph_ingest_work")
