"""ResearchNeed ANSWERED_BY KnowledgeClaim.

Revision ID: 117_knowledge_claim_answers
Revises: 116_knowledge_claims
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "117_knowledge_claim_answers"
down_revision: str | Sequence[str] | None = "116_knowledge_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_claim_answers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("research_need_id", sa.String(length=64), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["knowledge_claims.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "research_need_id",
            name="uq_knowledge_claim_answer_need",
        ),
    )
    op.create_index(
        "ix_knowledge_claim_answers_claim_id",
        "knowledge_claim_answers",
        ["claim_id"],
    )
    op.create_index(
        "ix_knowledge_claim_answers_research_need_id",
        "knowledge_claim_answers",
        ["research_need_id"],
    )
    op.create_index(
        "ix_knowledge_claim_answers_question_key",
        "knowledge_claim_answers",
        ["question_key"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_claim_answers")
