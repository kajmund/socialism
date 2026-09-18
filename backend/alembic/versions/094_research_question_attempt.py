"""Link a general research question to its child execution Attempt.

Revision ID: 094_research_question_attempt
Revises: 093_research_question_domain
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "094_research_question_attempt"
down_revision: str | Sequence[str] | None = "093_research_question_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("research_questions") as batch_op:
        batch_op.add_column(sa.Column("execution_attempt_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_research_questions_execution_attempt_id",
            "execution_attempts",
            ["execution_attempt_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_research_questions_execution_attempt_id",
            ["execution_attempt_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("research_questions") as batch_op:
        batch_op.drop_index("ix_research_questions_execution_attempt_id")
        batch_op.drop_constraint("fk_research_questions_execution_attempt_id", type_="foreignkey")
        batch_op.drop_column("execution_attempt_id")
