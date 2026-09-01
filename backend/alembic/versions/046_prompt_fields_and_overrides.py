"""Add prompt_fields catalog and sparse prompt_overrides.

Revision ID: 046_prompt_fields_and_overrides
Revises: 045_panel_session_panel_and_project

Standard unique constraints and real FKs — no SQLite-only partial indexes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046_prompt_fields_and_overrides"
down_revision: Union[str, Sequence[str], None] = "045_panel_session_panel_and_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_fields",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("modules", sa.JSON(), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("label_sv", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("label_en", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("hint_sv", sa.Text(), nullable=False, server_default=""),
        sa.Column("hint_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_sv", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_en", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_nb", sa.Text(), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_prompt_fields_key"),
    )

    op.create_table(
        "prompt_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("prompt_field_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["kunder.id"],
            name="fk_prompt_overrides_customer_id_kunder",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_field_id"],
            ["prompt_fields.id"],
            name="fk_prompt_overrides_prompt_field_id_prompt_fields",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id",
            "prompt_field_id",
            "language",
            name="uq_prompt_overrides_customer_field_language",
        ),
    )
    op.create_index(
        op.f("ix_prompt_overrides_customer_id"),
        "prompt_overrides",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_overrides_prompt_field_id"),
        "prompt_overrides",
        ["prompt_field_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_prompt_overrides_prompt_field_id"), table_name="prompt_overrides")
    op.drop_index(op.f("ix_prompt_overrides_customer_id"), table_name="prompt_overrides")
    op.drop_table("prompt_overrides")
    op.drop_table("prompt_fields")
