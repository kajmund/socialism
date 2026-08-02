"""Add results JSON column on runs for OASIS (and future) simulation output.

Revision ID: 003_run_results
Revises: 002_persona_messages
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_run_results"
down_revision: Union[str, Sequence[str], None] = "002_persona_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("results", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("results")
