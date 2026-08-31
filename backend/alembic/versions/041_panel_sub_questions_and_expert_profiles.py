"""Add panel_sub_questions and panel_expert_profiles tables.

Revision ID: 041_panel_sub_questions_and_expert_profiles
Revises: 040_dd_candidate_research
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "041_panel_sub_questions_and_expert_profiles"
down_revision: Union[str, Sequence[str], None] = "040_dd_candidate_research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "panel_sub_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("module", "key", name="uq_panel_sub_questions_module_key"),
    )
    op.create_index(
        op.f("ix_panel_sub_questions_module"),
        "panel_sub_questions",
        ["module"],
        unique=False,
    )

    op.create_table(
        "panel_expert_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("kompetensomrade", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("radgivningsstil", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("yrkesbakgrund", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("professionell_anekdot", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.UniqueConstraint("module", "key", name="uq_panel_expert_profiles_module_key"),
    )
    op.create_index(
        op.f("ix_panel_expert_profiles_module"),
        "panel_expert_profiles",
        ["module"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_panel_expert_profiles_module"), table_name="panel_expert_profiles")
    op.drop_table("panel_expert_profiles")
    op.drop_index(op.f("ix_panel_sub_questions_module"), table_name="panel_sub_questions")
    op.drop_table("panel_sub_questions")
