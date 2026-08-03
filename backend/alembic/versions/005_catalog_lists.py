"""Add catalog_lists table for grunddata configuration.

Revision ID: 005_catalog_lists
Revises: 004_messages
Create Date: 2026-08-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_catalog_lists"
down_revision: Union[str, Sequence[str], None] = "004_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_lists",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_catalog_lists_section", "catalog_lists", ["section"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_catalog_lists_section", table_name="catalog_lists")
    op.drop_table("catalog_lists")
