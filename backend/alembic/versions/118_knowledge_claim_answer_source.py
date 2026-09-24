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
    with op.batch_alter_table("knowledge_claim_answers") as batch:
        batch.add_column(sa.Column("source_type", sa.String(length=64), nullable=False))
        batch.add_column(
            sa.Column("knowledge_question_id", sa.String(length=64), nullable=True)
        )
        batch.create_index(
            "ix_knowledge_claim_answers_source_type",
            ["source_type"],
        )
        batch.create_index(
            "ix_knowledge_claim_answers_knowledge_question_id",
            ["knowledge_question_id"],
        )
        batch.create_foreign_key(
            "fk_knowledge_claim_answers_knowledge_question_id",
            "knowledge_questions",
            ["knowledge_question_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_claim_answers") as batch:
        batch.drop_constraint(
            "fk_knowledge_claim_answers_knowledge_question_id",
            type_="foreignkey",
        )
        batch.drop_index("ix_knowledge_claim_answers_knowledge_question_id")
        batch.drop_index("ix_knowledge_claim_answers_source_type")
        batch.drop_column("knowledge_question_id")
        batch.drop_column("source_type")
