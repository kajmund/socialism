"""dd_campaigns table for DD module.

Revision ID: 030_dd_campaigns
Revises: 029_run_live_progress
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_dd_campaigns"
down_revision: Union[str, Sequence[str], None] = "029_run_live_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dd_campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("selected_candidate_ids", sa.JSON(), nullable=False),
        sa.Column("expert_role_keys", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dd_campaigns_module"), "dd_campaigns", ["module"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dd_campaigns_module"), table_name="dd_campaigns")
    op.drop_table("dd_campaigns")
