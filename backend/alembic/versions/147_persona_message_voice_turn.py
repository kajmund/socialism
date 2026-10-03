"""Store one spoken expert-chat turn without a second memory write.

Revision ID: 147_persona_message_voice_turn
Revises: 146_lookup_research_evidence_tool
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "147_persona_message_voice_turn"
down_revision: str | Sequence[str] | None = "146_lookup_research_evidence_tool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.add_column(sa.Column("voice_turn_id", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_vturn",
            ["persona_id", "voice_turn_id", "role"],
        )


def downgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.drop_constraint("uq_vturn", type_="unique")
        batch_op.drop_column("voice_turn_id")
