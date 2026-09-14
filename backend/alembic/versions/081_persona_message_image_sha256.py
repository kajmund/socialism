"""Add image_sha256 to persona_messages for chat vision attachments.

Revision ID: 081_persona_message_image_sha256
Revises: 080_llm_runtime_settings
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "081_persona_message_image_sha256"
down_revision: Union[str, Sequence[str], None] = "080_llm_runtime_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "persona_messages",
        sa.Column("image_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persona_messages", "image_sha256")
