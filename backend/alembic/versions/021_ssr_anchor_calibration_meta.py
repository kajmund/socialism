"""SSR anchor set calibration metadata for publish gating.

Revision ID: 021_ssr_anchor_calibration_meta
Revises: 020_population_fingerprint_truth
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021_ssr_anchor_calibration_meta"
down_revision: Union[str, Sequence[str], None] = "020_population_fingerprint_truth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ssr_anchor_sets",
        sa.Column("calibration_accuracy", sa.Float(), nullable=True),
    )
    op.add_column(
        "ssr_anchor_sets",
        sa.Column("calibration_tested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ssr_anchor_sets",
        sa.Column("calibration_pool_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ssr_anchor_sets",
        sa.Column("calibration_n_at_test", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ssr_anchor_sets",
        sa.Column(
            "calibration_publish_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("ssr_anchor_sets", "calibration_publish_override")
    op.drop_column("ssr_anchor_sets", "calibration_n_at_test")
    op.drop_column("ssr_anchor_sets", "calibration_pool_revision")
    op.drop_column("ssr_anchor_sets", "calibration_tested_at")
    op.drop_column("ssr_anchor_sets", "calibration_accuracy")
