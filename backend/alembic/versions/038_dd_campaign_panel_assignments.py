"""Add panel_assignments to dd_campaigns.

Revision ID: 038_dd_campaign_panel_assignments
Revises: 037_dd_campaign_expert_panel_id
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "038_dd_campaign_panel_assignments"
down_revision: Union[str, Sequence[str], None] = "037_dd_campaign_expert_panel_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dd_campaigns") as batch_op:
        batch_op.add_column(
            sa.Column("panel_assignments", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    with op.batch_alter_table("dd_campaigns") as batch_op:
        batch_op.drop_column("panel_assignments")
