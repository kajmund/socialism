"""Add locale column on reports for Swedish/English HTML variants.

Revision ID: 010_report_locale
Revises: 009_persona_messages_run_scope
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_report_locale"
down_revision: Union[str, Sequence[str], None] = "009_persona_messages_run_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="sv"),
    )


def downgrade() -> None:
    op.drop_column("reports", "locale")
