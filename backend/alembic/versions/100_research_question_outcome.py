"""Persist question-level research outcomes.

Revision ID: 100_research_question_outcome
Revises: 099_persona_message_expert_turn
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "100_research_question_outcome"
down_revision: str | Sequence[str] | None = "099_persona_message_expert_turn"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("research_questions") as batch_op:
        batch_op.add_column(sa.Column("outcome_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("research_questions") as batch_op:
        batch_op.drop_column("outcome_reason")
