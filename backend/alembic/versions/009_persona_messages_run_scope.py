"""Add run-scoped columns on persona_messages for post-hoc interviews.

Revision ID: 009_persona_messages_run_scope
Revises: 008_run_oasis_options
Create Date: 2026-08-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_persona_messages_run_scope"
down_revision: Union[str, Sequence[str], None] = "008_run_oasis_options"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "persona_messages",
        sa.Column("run_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "persona_messages",
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "persona_messages",
        sa.Column("variant_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "persona_messages",
        sa.Column("through_tick_index", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_persona_messages_run_scope",
        "persona_messages",
        ["persona_id", "run_id", "attempt_id", "variant_id", "through_tick_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_persona_messages_run_scope", table_name="persona_messages")
    op.drop_column("persona_messages", "through_tick_index")
    op.drop_column("persona_messages", "variant_id")
    op.drop_column("persona_messages", "attempt_id")
    op.drop_column("persona_messages", "run_id")
