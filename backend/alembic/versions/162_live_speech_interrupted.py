"""Mark interrupted assistant turns.

Revision ID: 162_live_speech_interrupted
Revises: 161_persona_message_reasoning
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "162_live_speech_interrupted"
down_revision: str | Sequence[str] | None = "161_persona_message_reasoning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.add_column(
            sa.Column("interrupted", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.drop_column("interrupted")
