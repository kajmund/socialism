"""Replace configuration.prompt_text with prompts JSON + is_active.

Revision ID: 012_configuration_prompts_map
Revises: 011_configurations
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_configuration_prompts_map"
down_revision: Union[str, Sequence[str], None] = "011_configurations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("configurations") as batch:
        batch.add_column(
            sa.Column("prompts", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.drop_column("prompt_text")


def downgrade() -> None:
    with op.batch_alter_table("configurations") as batch:
        batch.add_column(
            sa.Column("prompt_text", sa.Text(), nullable=False, server_default="")
        )
        batch.drop_column("is_active")
        batch.drop_column("prompts")
