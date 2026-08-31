"""Add research dossier columns to dd_candidate_runs.

Revision ID: 040_dd_candidate_research
Revises: 039_persona_tools
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "040_dd_candidate_research"
down_revision: Union[str, Sequence[str], None] = "039_persona_tools"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dd_candidate_runs") as batch_op:
        batch_op.add_column(sa.Column("research", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("research_job_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dd_candidate_runs") as batch_op:
        batch_op.drop_column("research_job_id")
        batch_op.drop_column("research")
