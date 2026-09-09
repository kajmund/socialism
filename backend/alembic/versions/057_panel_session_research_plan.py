"""Add research_plan JSON on panel_sessions.

Revision ID: 057_panel_session_research_plan
Revises: 056_word_moderator_batch
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "057_panel_session_research_plan"
down_revision: Union[str, Sequence[str], None] = "056_word_moderator_batch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("panel_sessions", sa.Column("research_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("panel_sessions", "research_plan")
