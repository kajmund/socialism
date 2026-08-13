"""spindoctor_messages table for report-scoped Spinndoktor chat.

Revision ID: 024_spindoctor_messages
Revises: 023_report_verdict_calibrations
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_spindoctor_messages"
down_revision: Union[str, Sequence[str], None] = "023_report_verdict_calibrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spindoctor_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_spindoctor_messages_report_id",
        "spindoctor_messages",
        ["report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_spindoctor_messages_report_id", table_name="spindoctor_messages")
    op.drop_table("spindoctor_messages")
