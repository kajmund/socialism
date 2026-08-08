"""Add ssr_temperature on configurations.

Revision ID: 015_configuration_ssr_temperature
Revises: 014_report_mode
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_configuration_ssr_temperature"
down_revision: Union[str, Sequence[str], None] = "014_report_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "configurations",
        sa.Column(
            "ssr_temperature",
            sa.Float(),
            nullable=False,
            server_default="0.1",
        ),
    )


def downgrade() -> None:
    op.drop_column("configurations", "ssr_temperature")
