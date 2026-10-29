"""Optional per-expert live voice model for the OpenAI native-audio provider.

Revision ID: 194_live_voice_model
Revises: 193_tabular_reviews

The GUI offers the newest OpenAI Realtime speech-to-speech models per expert.
Null falls back to the process default (OPENAI_NATIVE_MODEL).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "194_live_voice_model"
down_revision: str | Sequence[str] | None = "193_tabular_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column("live_voice_model", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("personas", "live_voice_model")
