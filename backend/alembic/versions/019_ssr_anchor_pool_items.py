"""SSR anchor pool items + pool_revision on anchor sets.

Revision ID: 019_ssr_anchor_pool_items
Revises: 018_feedback_items
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_ssr_anchor_pool_items"
down_revision: Union[str, Sequence[str], None] = "018_feedback_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ssr_anchor_sets",
        sa.Column("pool_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "ssr_anchor_pool_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("anchor_set_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("source_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("source_variant_id", sa.String(length=64), nullable=True),
        sa.Column("source_ref", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["anchor_set_id"],
            ["ssr_anchor_sets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "anchor_set_id",
            "label",
            "text",
            name="uq_ssr_anchor_pool_set_label_text",
        ),
    )
    op.create_index(
        "ix_ssr_anchor_pool_items_anchor_set_id",
        "ssr_anchor_pool_items",
        ["anchor_set_id"],
    )
    op.create_index(
        "ix_ssr_anchor_pool_items_source_run_id",
        "ssr_anchor_pool_items",
        ["source_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ssr_anchor_pool_items_source_run_id", table_name="ssr_anchor_pool_items")
    op.drop_index("ix_ssr_anchor_pool_items_anchor_set_id", table_name="ssr_anchor_pool_items")
    op.drop_table("ssr_anchor_pool_items")
    op.drop_column("ssr_anchor_sets", "pool_revision")
