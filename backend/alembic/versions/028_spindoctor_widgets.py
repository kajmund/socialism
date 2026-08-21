"""spindoctor_widgets table for report-scoped Spinndoktor boards.

Revision ID: 028_spindoctor_widgets
Revises: 027_persona_message_asked_by
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028_spindoctor_widgets"
down_revision: Union[str, Sequence[str], None] = "027_persona_message_asked_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spindoctor_widgets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("pos_x", sa.Float(), nullable=False),
        sa.Column("pos_y", sa.Float(), nullable=False),
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
        "ix_spindoctor_widgets_report_id",
        "spindoctor_widgets",
        ["report_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_spindoctor_widgets_report_id", table_name="spindoctor_widgets")
    op.drop_table("spindoctor_widgets")
