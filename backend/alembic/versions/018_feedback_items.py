"""feedback_items table for help-bot bugs/ideas/opinions.

Revision ID: 018_feedback_items
Revises: 017_help_messages
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_feedback_items"
down_revision: Union[str, Sequence[str], None] = "017_help_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("view_path", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_items_kind", "feedback_items", ["kind"])
    op.create_index("ix_feedback_items_status", "feedback_items", ["status"])
    op.create_index("ix_feedback_items_created_at", "feedback_items", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_items_created_at", table_name="feedback_items")
    op.drop_index("ix_feedback_items_status", table_name="feedback_items")
    op.drop_index("ix_feedback_items_kind", table_name="feedback_items")
    op.drop_table("feedback_items")
