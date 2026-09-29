"""Fact-edge revalidation dependencies and durable candidate queue."""

import sqlalchemy as sa
from alembic import op

revision = "138_graph_fact_revalidation"
down_revision = "137_graph_v2_reconcile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_fact_question_dependencies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("question_node_id", sa.String(64), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_id", sa.String(64), sa.ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("question_node_id", "fact_id", name="uq_graph_fact_question_dependency"),
    )
    op.create_index("ix_graph_fact_question_dependency_fact", "graph_fact_question_dependencies", ["fact_id"])
    op.create_table(
        "graph_fact_revalidations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("trigger_fact_id", sa.String(64), sa.ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dependent_fact_id", sa.String(64), sa.ForeignKey("graph_facts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_node_id", sa.String(64), sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_provenance", sa.JSON(), nullable=False),
        sa.Column("dependent_provenance", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("trigger_fact_id", "dependent_fact_id", "question_node_id", name="uq_graph_fact_revalidation_candidate"),
    )
    op.create_index("ix_graph_fact_revalidation_pending", "graph_fact_revalidations", ["status", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE graph_fact_question_dependencies ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE graph_fact_revalidations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("graph_fact_revalidations")
    op.drop_table("graph_fact_question_dependencies")
