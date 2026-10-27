"""Per-expert STT-correction settings for Socialism live voice.

Revision ID: 195_stt_correction
Revises: 194_live_voice_model

Null means the process default (enabled, 2.0 s timeout). Only the workspace
live-speech path (provider "socialism") reads these columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "195_stt_correction"
down_revision: str | Sequence[str] | None = "194_live_voice_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column("stt_correction_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "personas",
        sa.Column("stt_correction_timeout_seconds", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("personas", "stt_correction_timeout_seconds")
    op.drop_column("personas", "stt_correction_enabled")
