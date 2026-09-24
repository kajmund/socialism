"""KnowledgeQuestion DAG lineage and iterative research freeze refs.

Revision ID: 122_knowledge_question_iteration
Revises: 121_evidence_revalidation
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "122_knowledge_question_iteration"
down_revision: str | Sequence[str] | None = "121_evidence_revalidation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_question_lineage",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("parent_question_id", sa.String(length=64), nullable=False),
        sa.Column("child_question_id", sa.String(length=64), nullable=False),
        sa.Column("trigger_claim_id", sa.String(length=64), nullable=True),
        sa.Column("trigger_graph_event_id", sa.String(length=64), nullable=True),
        sa.Column("why_needed", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_question_id"],
            ["knowledge_questions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["child_question_id"],
            ["knowledge_questions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_claim_id"],
            ["knowledge_claims.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_graph_event_id"],
            ["knowledge_graph_events.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_question_id",
            "child_question_id",
            name="uq_knowledge_question_lineage_edge",
        ),
    )
    op.create_index(
        "ix_knowledge_question_lineage_parent_question_id",
        "knowledge_question_lineage",
        ["parent_question_id"],
    )
    op.create_index(
        "ix_knowledge_question_lineage_child",
        "knowledge_question_lineage",
        ["child_question_id"],
    )
    op.create_index(
        "ix_knowledge_question_lineage_trigger_claim_id",
        "knowledge_question_lineage",
        ["trigger_claim_id"],
    )
    with op.batch_alter_table("research_runtime_needs") as batch:
        batch.add_column(
            sa.Column("knowledge_question_id", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("generated_from_question_id", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("trigger_claim_id", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("trigger_graph_event_id", sa.String(length=64), nullable=True)
        )
        batch.create_index(
            "ix_research_runtime_needs_knowledge_question_id",
            ["knowledge_question_id"],
        )
        batch.create_index(
            "ix_research_runtime_needs_generated_from_question_id",
            ["generated_from_question_id"],
        )
        batch.create_foreign_key(
            "fk_research_runtime_needs_knowledge_question_id",
            "knowledge_questions",
            ["knowledge_question_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_research_runtime_needs_generated_from_question_id",
            "knowledge_questions",
            ["generated_from_question_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_research_runtime_needs_trigger_claim_id",
            "knowledge_claims",
            ["trigger_claim_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_research_runtime_needs_trigger_graph_event_id",
            "knowledge_graph_events",
            ["trigger_graph_event_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("evidence_sets") as batch:
        batch.add_column(sa.Column("grounded_refs", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("evidence_sets") as batch:
        batch.drop_column("grounded_refs")
    with op.batch_alter_table("research_runtime_needs") as batch:
        batch.drop_constraint(
            "fk_research_runtime_needs_trigger_graph_event_id",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_research_runtime_needs_trigger_claim_id",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_research_runtime_needs_generated_from_question_id",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_research_runtime_needs_knowledge_question_id",
            type_="foreignkey",
        )
        batch.drop_index("ix_research_runtime_needs_generated_from_question_id")
        batch.drop_index("ix_research_runtime_needs_knowledge_question_id")
        batch.drop_column("trigger_graph_event_id")
        batch.drop_column("trigger_claim_id")
        batch.drop_column("generated_from_question_id")
        batch.drop_column("knowledge_question_id")
    op.drop_table("knowledge_question_lineage")
