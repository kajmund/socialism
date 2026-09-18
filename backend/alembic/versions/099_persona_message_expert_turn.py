"""Bind library chat rows to an SME expert-turn request_id.

Revision ID: 099_persona_message_expert_turn
Revises: 098_sme_chat_turn_state
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "099_persona_message_expert_turn"
down_revision: str | Sequence[str] | None = "098_sme_chat_turn_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.add_column(
            sa.Column("sme_expert_turn_request_id", sa.String(length=64), nullable=True)
        )
        batch_op.create_index(
            "ix_persona_messages_sme_expert_turn_request_id",
            ["sme_expert_turn_request_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_persona_messages_sme_expert_turn_request_id",
            "sme_expert_turns",
            ["sme_expert_turn_request_id"],
            ["request_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.drop_constraint(
            "fk_persona_messages_sme_expert_turn_request_id",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_persona_messages_sme_expert_turn_request_id")
        batch_op.drop_column("sme_expert_turn_request_id")
