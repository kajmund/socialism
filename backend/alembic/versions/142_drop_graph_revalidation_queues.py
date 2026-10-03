"""Drop unused Graph v2 question/fact revalidation queues.

Keeps graph_fact_question_dependencies: research reuse still reads those edges.
"""

import sqlalchemy as sa
from alembic import op

revision = "142_drop_graph_revalidation_queues"
down_revision = "e8c2f4a1b6d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("graph_question_revalidation_work")
    op.drop_table("graph_fact_revalidations")


def downgrade() -> None:
    op.create_table(
        "graph_fact_revalidations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column(
            "trigger_fact_id",
            sa.String(64),
            sa.ForeignKey("graph_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dependent_fact_id",
            sa.String(64),
            sa.ForeignKey("graph_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_node_id",
            sa.String(64),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger_provenance", sa.JSON(), nullable=False),
        sa.Column("dependent_provenance", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "trigger_fact_id",
            "dependent_fact_id",
            "question_node_id",
            name="uq_graph_fact_revalidation_candidate",
        ),
    )
    op.create_index(
        "ix_graph_fact_revalidation_pending",
        "graph_fact_revalidations",
        ["status", "created_at"],
    )
    op.create_table(
        "graph_question_revalidation_work",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column(
            "question_node_id",
            sa.String(64),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_set_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "scope_key",
            "question_node_id",
            "evidence_set_id",
            name="uq_graph_question_revalidation_work",
        ),
    )
    op.create_index(
        "ix_graph_question_revalidation_pending",
        "graph_question_revalidation_work",
        ["status", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE graph_fact_revalidations ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE graph_question_revalidation_work ENABLE ROW LEVEL SECURITY")
