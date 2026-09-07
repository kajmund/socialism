"""Add expertgranskning_results for Word paragraph review.

Revision ID: 052_expertgranskning_results
Revises: 051_underlag_folders
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052_expertgranskning_results"
down_revision: Union[str, Sequence[str], None] = "051_underlag_folders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expertgranskning_results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("paragraph_index", sa.Integer(), nullable=False),
        sa.Column("expert_id", sa.String(length=64), nullable=False),
        sa.Column("expert_namn", sa.String(length=255), nullable=False),
        sa.Column("kommentar", sa.Text(), nullable=False),
        sa.Column("is_heading_suggestion", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("comment_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_expertgranskning_results_job_id",
        "expertgranskning_results",
        ["job_id"],
    )
    op.create_index(
        "ix_expertgranskning_results_customer_id",
        "expertgranskning_results",
        ["customer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_expertgranskning_results_customer_id",
        table_name="expertgranskning_results",
    )
    op.drop_index(
        "ix_expertgranskning_results_job_id",
        table_name="expertgranskning_results",
    )
    op.drop_table("expertgranskning_results")
