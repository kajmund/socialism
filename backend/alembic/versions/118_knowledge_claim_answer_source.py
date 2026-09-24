"""Claim answers carry source_type and KnowledgeQuestion id.

Revision ID: 118_knowledge_claim_answer_source
Revises: 117_knowledge_claim_answers
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "118_knowledge_claim_answer_source"
down_revision: str | Sequence[str] | None = "117_knowledge_claim_answers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_claim_answers",
        sa.Column("source_type", sa.String(length=64), nullable=False),
    )
    op.add_column(
        "knowledge_claim_answers",
        sa.Column("knowledge_question_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_knowledge_claim_answers_source_type",
        "knowledge_claim_answers",
        ["source_type"],
    )
    op.create_index(
        "ix_knowledge_claim_answers_knowledge_question_id",
        "knowledge_claim_answers",
        ["knowledge_question_id"],
    )
    op.create_foreign_key(
        "fk_knowledge_claim_answers_knowledge_question_id",
        "knowledge_claim_answers",
        "knowledge_questions",
        ["knowledge_question_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_knowledge_claim_answers_knowledge_question_id",
        "knowledge_claim_answers",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_knowledge_claim_answers_knowledge_question_id",
        table_name="knowledge_claim_answers",
    )
    op.drop_index(
        "ix_knowledge_claim_answers_source_type",
        table_name="knowledge_claim_answers",
    )
    op.drop_column("knowledge_claim_answers", "knowledge_question_id")
    op.drop_column("knowledge_claim_answers", "source_type")
