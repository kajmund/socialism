"""Add customer product and SME Messenger persistence.

Revision ID: 096_sme_product_messenger
Revises: 095_expert_research_tool
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "096_sme_product_messenger"
down_revision: str | Sequence[str] | None = "095_expert_research_tool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("kunder", sa.Column("product", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_kunder_product"), "kunder", ["product"], unique=False)
    op.create_table(
        "sme_panel_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("population_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("persona_id", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["kunder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["population_id"], ["populations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sme_panel_messages_customer_id"),
        "sme_panel_messages",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sme_panel_messages_population_id"),
        "sme_panel_messages",
        ["population_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sme_panel_messages_persona_id"),
        "sme_panel_messages",
        ["persona_id"],
        unique=False,
    )
    op.create_table(
        "sme_read_cursors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("thread_type", sa.String(length=16), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("last_read_message_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "thread_type",
            "thread_id",
            name="uq_sme_read_cursors_user_thread",
        ),
    )
    op.create_index(
        op.f("ix_sme_read_cursors_user_id"),
        "sme_read_cursors",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sme_read_cursors_user_id"), table_name="sme_read_cursors")
    op.drop_table("sme_read_cursors")
    op.drop_index(
        op.f("ix_sme_panel_messages_persona_id"),
        table_name="sme_panel_messages",
    )
    op.drop_index(
        op.f("ix_sme_panel_messages_population_id"),
        table_name="sme_panel_messages",
    )
    op.drop_index(
        op.f("ix_sme_panel_messages_customer_id"),
        table_name="sme_panel_messages",
    )
    op.drop_table("sme_panel_messages")
    op.drop_index(op.f("ix_kunder_product"), table_name="kunder")
    op.drop_column("kunder", "product")
