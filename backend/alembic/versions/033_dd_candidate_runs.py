"""dd_candidate_runs — persist candidate panel/report links per campaign.

Revision ID: 033_dd_candidate_runs
Revises: 032_panel_session_result
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033_dd_candidate_runs"
down_revision = "032_panel_session_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dd_candidate_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("panel_session_id", sa.String(length=64), nullable=True),
        sa.Column("report_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["dd_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["panel_session_id"], ["panel_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "candidate_id",
            name="uq_dd_candidate_runs_campaign_candidate",
        ),
    )
    op.create_index(
        op.f("ix_dd_candidate_runs_campaign_id"),
        "dd_candidate_runs",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dd_candidate_runs_campaign_id"), table_name="dd_candidate_runs")
    op.drop_table("dd_candidate_runs")
