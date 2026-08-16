"""ssr_misclassification_flags — SSR wrong-prediction operator flags.

Revision ID: 026_ssr_misclassification_flags
Revises: 025_ssr_label_vocabularies
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "026_ssr_misclassification_flags"
down_revision: Union[str, Sequence[str], None] = "025_ssr_label_vocabularies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ssr_misclassification_flags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("anchor_set_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("predicted_label", sa.String(length=64), nullable=False),
        sa.Column("expected_label", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("source_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("source_variant_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("pool_item_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["pool_item_id"],
            ["ssr_anchor_pool_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ssr_misclassification_flags_anchor_set_id",
        "ssr_misclassification_flags",
        ["anchor_set_id"],
    )
    op.create_index(
        "ix_ssr_misclassification_flags_kind",
        "ssr_misclassification_flags",
        ["kind"],
    )
    op.create_index(
        "ix_ssr_misclassification_flags_source_run_id",
        "ssr_misclassification_flags",
        ["source_run_id"],
    )
    op.create_index(
        "ix_ssr_misclassification_flags_status",
        "ssr_misclassification_flags",
        ["status"],
    )
    op.create_index(
        "ix_ssr_misclassification_flags_pool_item_id",
        "ssr_misclassification_flags",
        ["pool_item_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ssr_misclassification_flags_pool_item_id",
        table_name="ssr_misclassification_flags",
    )
    op.drop_index(
        "ix_ssr_misclassification_flags_status",
        table_name="ssr_misclassification_flags",
    )
    op.drop_index(
        "ix_ssr_misclassification_flags_source_run_id",
        table_name="ssr_misclassification_flags",
    )
    op.drop_index(
        "ix_ssr_misclassification_flags_kind",
        table_name="ssr_misclassification_flags",
    )
    op.drop_index(
        "ix_ssr_misclassification_flags_anchor_set_id",
        table_name="ssr_misclassification_flags",
    )
    op.drop_table("ssr_misclassification_flags")
