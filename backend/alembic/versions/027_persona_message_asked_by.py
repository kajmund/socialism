"""Add asked_by on persona_messages for interview attribution.

Revision ID: 027_persona_message_asked_by
Revises: 026_ssr_misclassification_flags
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027_persona_message_asked_by"
down_revision: Union[str, Sequence[str], None] = "026_ssr_misclassification_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "persona_messages",
        sa.Column("asked_by", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persona_messages", "asked_by")
