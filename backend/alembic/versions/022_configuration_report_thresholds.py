"""Add report_thresholds JSON on configurations.

Revision ID: 022_configuration_report_thresholds
Revises: 021_ssr_anchor_calibration_meta
Create Date: 2026-08-11
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_configuration_report_thresholds"
down_revision: Union[str, Sequence[str], None] = "021_ssr_anchor_calibration_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_JSON = json.dumps(
    {
        "verdict": {"pos_strong": 0.50, "pos_mixed": 0.30, "crit_weak": 0.50},
        "diff": {"clear": 0.08, "weak": 0.03},
        "topic_drift": 0.10,
        "recommendation": {
            "score_weights": {
                "positive": 45.0,
                "critical_headroom": 25.0,
                "injection_likes": 15.0,
                "engagement": 15.0,
            },
            "score_caps": {
                "zero_likes_max": 15.0,
                "strong_floor": 65.0,
                "weak_ceiling": 45.0,
                "injection_likes_cap": 20,
                "engagement_cap": 80,
            },
            "score_triggers": {
                "strong_pos": 0.45,
                "strong_crit_max": 0.45,
                "weak_pos_max": 0.25,
                "crit_baseline": 0.35,
            },
            "action_bands": {"ready": 75, "minor_adjust": 55, "revise": 35},
            "narrative": {
                "good_reception_pos": 0.35,
                "high_crit": 0.45,
                "segment_pos": 0.45,
                "segment_crit": 0.50,
            },
        },
    },
    separators=(",", ":"),
)


def upgrade() -> None:
    op.add_column(
        "configurations",
        sa.Column(
            "report_thresholds",
            sa.JSON(),
            nullable=False,
            server_default=_DEFAULT_JSON,
        ),
    )


def downgrade() -> None:
    op.drop_column("configurations", "report_thresholds")
