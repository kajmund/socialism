"""Move expert library chat from interview mode to in-character.

Revision ID: 164_expert_chat_in_character
Revises: 163_document_generation_conversation
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "164_expert_chat_in_character"
down_revision: str | Sequence[str] | None = "163_document_generation_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE persona_messages
        SET mode = 'character'
        WHERE mode = 'interview'
          AND run_id IS NULL
          AND persona_id IN (SELECT id FROM personas WHERE kind = 'expert')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE persona_messages
        SET mode = 'interview'
        WHERE mode = 'character'
          AND run_id IS NULL
          AND persona_id IN (SELECT id FROM personas WHERE kind = 'expert')
        """
    )
