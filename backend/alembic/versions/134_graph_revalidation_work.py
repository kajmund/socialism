"""durable graph revalidation work, off the retrieval path

Revision ID: 134_graph_revalidation_work
Revises: 133_decomposition_exhaustion
Create Date: 2026-09-27

Committed claims enqueue one idempotent row. Retrieval does not wait for it.
A restarted process retries pending and expired leases.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "134_graph_revalidation_work"
down_revision: str | Sequence[str] | None = "133_decomposition_exhaustion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_revalidation_work",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=True),
        sa.Column("document_version_id", sa.String(length=64), nullable=True),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("relationship_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_id", sa.String(length=64), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("events_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_graph_revalidation_work_key"),
    )
    op.create_index(
        "ix_graph_revalidation_work_customer_id",
        "graph_revalidation_work",
        ["customer_id"],
    )
    op.create_index(
        "ix_graph_revalidation_work_status_lease",
        "graph_revalidation_work",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_graph_revalidation_work_status_lease",
        table_name="graph_revalidation_work",
    )
    op.drop_index(
        "ix_graph_revalidation_work_customer_id",
        table_name="graph_revalidation_work",
    )
    op.drop_table("graph_revalidation_work")
