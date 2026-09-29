"""Durable graph review requests created at final research freeze."""

import sqlalchemy as sa
from alembic import op

revision = "139_graph_question_revalidation_work"
down_revision = "138_graph_fact_revalidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_question_revalidation_work",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("question_node_id", sa.String(64), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_set_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("scope_key", "question_node_id", "evidence_set_id", name="uq_graph_question_revalidation_work"),
    )
    op.create_index("ix_graph_question_revalidation_pending", "graph_question_revalidation_work", ["status", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE graph_question_revalidation_work ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("graph_question_revalidation_work")
