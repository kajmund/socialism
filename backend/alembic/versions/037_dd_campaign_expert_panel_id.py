"""Add expert_panel_id to dd_campaigns.

Revision ID: 037_dd_campaign_expert_panel_id
Revises: 036_persona_population_kind_job_report_customer
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037_dd_campaign_expert_panel_id"
down_revision: Union[str, Sequence[str], None] = "036_persona_population_kind_job_report_customer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dd_campaigns") as batch_op:
        batch_op.add_column(sa.Column("expert_panel_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_dd_campaigns_expert_panel_id_populations",
            "populations",
            ["expert_panel_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_dd_campaigns_expert_panel_id", ["expert_panel_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("dd_campaigns") as batch_op:
        batch_op.drop_index("ix_dd_campaigns_expert_panel_id")
        batch_op.drop_constraint("fk_dd_campaigns_expert_panel_id_populations", type_="foreignkey")
        batch_op.drop_column("expert_panel_id")
