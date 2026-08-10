"""help_messages table for in-app help chat.

Revision ID: 017_help_messages
Revises: 016_ssr_anchor_library
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_help_messages"
down_revision: Union[str, Sequence[str], None] = "016_ssr_anchor_library"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "help_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_help_messages_session_id", "help_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_help_messages_session_id", table_name="help_messages")
    op.drop_table("help_messages")
