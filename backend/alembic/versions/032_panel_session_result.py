"""Add structured result JSON to panel_sessions (dd_panel output).

Revision ID: 032_panel_session_result
Revises: 031_panel_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "032_panel_session_result"
down_revision = "031_panel_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("panel_sessions", sa.Column("result", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("panel_sessions", "result")
