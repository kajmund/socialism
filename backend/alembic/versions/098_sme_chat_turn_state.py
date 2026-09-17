"""Persist SME panel leases and expert-chat turn state.

Revision ID: 098_sme_chat_turn_state
Revises: 097_repair_cross_customer_expert_panels
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "098_sme_chat_turn_state"
down_revision: str | Sequence[str] | None = "097_repair_cross_customer_expert_panels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sme_panel_turn_leases",
        sa.Column("panel_id", sa.Integer(), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["panel_id"], ["populations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("panel_id"),
    )
    op.create_index(
        op.f("ix_sme_panel_turn_leases_lease_expires_at"),
        "sme_panel_turn_leases",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "sme_expert_turns",
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("persona_id", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index(
        op.f("ix_sme_expert_turns_customer_id"),
        "sme_expert_turns",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sme_expert_turns_user_id"),
        "sme_expert_turns",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sme_expert_turns_persona_id"),
        "sme_expert_turns",
        ["persona_id"],
        unique=False,
    )
    op.create_index(
        "ix_sme_expert_turns_user_persona",
        "sme_expert_turns",
        ["user_id", "persona_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sme_expert_turns_user_persona", table_name="sme_expert_turns")
    op.drop_index(op.f("ix_sme_expert_turns_persona_id"), table_name="sme_expert_turns")
    op.drop_index(op.f("ix_sme_expert_turns_user_id"), table_name="sme_expert_turns")
    op.drop_index(op.f("ix_sme_expert_turns_customer_id"), table_name="sme_expert_turns")
    op.drop_table("sme_expert_turns")
    op.drop_index(
        op.f("ix_sme_panel_turn_leases_lease_expires_at"),
        table_name="sme_panel_turn_leases",
    )
    op.drop_table("sme_panel_turn_leases")
