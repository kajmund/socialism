"""panel_sessions table.

Revision ID: 031_panel_sessions
Revises: 030_dd_campaigns
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031_panel_sessions"
down_revision: Union[str, Sequence[str], None] = "030_dd_campaigns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "panel_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("scratchpads", sa.JSON(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["dd_campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_panel_sessions_campaign_id"), "panel_sessions", ["campaign_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_panel_sessions_campaign_id"), table_name="panel_sessions")
    op.drop_table("panel_sessions")
