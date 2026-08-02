"""Add persona_messages for interview / in-character chat.

Revision ID: 002_persona_messages
Revises: 001_initial
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_persona_messages"
down_revision: Union[str, Sequence[str], None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "persona_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("persona_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_persona_messages_persona_id"),
        "persona_messages",
        ["persona_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_persona_messages_persona_id"), table_name="persona_messages")
    op.drop_table("persona_messages")
