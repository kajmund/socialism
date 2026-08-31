"""Add user_accounts for Supabase Auth role + kund binding.

Revision ID: 045_user_accounts
Revises: 044_panel_expert_profiles_shared_modules
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "045_user_accounts"
down_revision: Union[str, Sequence[str], None] = "044_panel_expert_profiles_shared_modules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("kund_id", sa.Integer(), nullable=True),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["kund_id"], ["kunder.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_user_accounts_email"), "user_accounts", ["email"], unique=False)
    op.create_index(op.f("ix_user_accounts_kund_id"), "user_accounts", ["kund_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_accounts_kund_id"), table_name="user_accounts")
    op.drop_index(op.f("ix_user_accounts_email"), table_name="user_accounts")
    op.drop_table("user_accounts")
