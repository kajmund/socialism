"""Frozen EvidenceSet revalidation state.

Revision ID: 121_evidence_revalidation
Revises: 120_knowledge_graph_events
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "121_evidence_revalidation"
down_revision: str | Sequence[str] | None = "120_knowledge_graph_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_sets",
        sa.Column("graph_revision_at_freeze", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "evidence_set_revalidations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("evidence_set_id", sa.String(length=64), nullable=False),
        sa.Column("graph_event_id", sa.String(length=64), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=True),
        sa.Column("knowledge_question_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("impact_noul", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_set_id"], ["evidence_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["graph_event_id"],
            ["knowledge_graph_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_question_id"],
            ["knowledge_questions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_set_id",
            "graph_event_id",
            name="uq_evidence_set_revalidation_event",
        ),
    )
    op.create_index(
        "ix_evidence_set_revalidations_evidence_set_id",
        "evidence_set_revalidations",
        ["evidence_set_id"],
    )
    op.create_index(
        "ix_evidence_set_revalidations_graph_event_id",
        "evidence_set_revalidations",
        ["graph_event_id"],
    )
    op.create_index(
        "ix_evidence_set_revalidations_state",
        "evidence_set_revalidations",
        ["state"],
    )


def downgrade() -> None:
    op.drop_table("evidence_set_revalidations")
    op.drop_column("evidence_sets", "graph_revision_at_freeze")
