"""Add available_modules to kunder.

Revision ID: 042_kund_available_modules
Revises: 041_panel_sub_questions_and_expert_profiles
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042_kund_available_modules"
down_revision: Union[str, Sequence[str], None] = "041_panel_sub_questions_and_expert_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("kunder") as batch_op:
        batch_op.add_column(
            sa.Column(
                "available_modules",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )
    kunder = sa.table(
        "kunder",
        sa.column("slug", sa.String),
        sa.column("available_modules", sa.JSON),
    )
    op.execute(kunder.update().where(kunder.c.slug == "devbrains").values(available_modules=["politik"]))
    op.execute(kunder.update().where(kunder.c.slug == "bolag-demo").values(available_modules=["dd"]))


def downgrade() -> None:
    with op.batch_alter_table("kunder") as batch_op:
        batch_op.drop_column("available_modules")
