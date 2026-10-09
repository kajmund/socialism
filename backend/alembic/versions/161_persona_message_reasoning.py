"""Store DeepSeek thinking text on assistant chat rows.

Revision ID: 161_persona_message_reasoning
Revises: 160_document_tool_retrieval
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "161_persona_message_reasoning"
down_revision: str | Sequence[str] | None = "160_document_tool_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.add_column(sa.Column("reasoning_content", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("persona_messages") as batch_op:
        batch_op.drop_column("reasoning_content")
