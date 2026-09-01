"""Add panel_id and project_id on panel_sessions.

Revision ID: 045_panel_session_panel_and_project
Revises: 044_panel_expert_profiles_shared_modules

panel_id → populations.id (expert_panel). project_id → projekt.id.
campaign_id stays as the DD-specific extra. No backfill — existing rows stay NULL.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "045_panel_session_panel_and_project"
down_revision: Union[str, Sequence[str], None] = "044_panel_expert_profiles_shared_modules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("panel_sessions") as batch_op:
        batch_op.add_column(sa.Column("panel_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_panel_sessions_panel_id_populations",
            "populations",
            ["panel_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_panel_sessions_project_id_projekt",
            "projekt",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_panel_sessions_panel_id", ["panel_id"], unique=False)
        batch_op.create_index("ix_panel_sessions_project_id", ["project_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("panel_sessions") as batch_op:
        batch_op.drop_index("ix_panel_sessions_project_id")
        batch_op.drop_index("ix_panel_sessions_panel_id")
        batch_op.drop_constraint("fk_panel_sessions_project_id_projekt", type_="foreignkey")
        batch_op.drop_constraint("fk_panel_sessions_panel_id_populations", type_="foreignkey")
        batch_op.drop_column("project_id")
        batch_op.drop_column("panel_id")
