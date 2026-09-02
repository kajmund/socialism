"""Add archived_at to jobs so finished work can leave the default list.

Revision ID: 046_job_archived_at
Revises: 045_user_accounts
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046_job_archived_at"
down_revision: Union[str, Sequence[str], None] = "045_user_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_jobs_archived_at", ["archived_at"])


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_archived_at")
        batch_op.drop_column("archived_at")
