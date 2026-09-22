"""Prompt LLM selection mode and Auto metadata on configurations.

Revision ID: 113_llm_selection_mode
Revises: 112_llm_configurations
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "113_llm_selection_mode"
down_revision: Union[str, Sequence[str], None] = "112_llm_configurations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_fields") as batch:
        batch.add_column(
            sa.Column(
                "llm_selection_mode",
                sa.String(length=16),
                nullable=False,
                server_default="default",
            )
        )
        batch.create_index(
            "ix_prompt_fields_llm_selection_mode",
            ["llm_selection_mode"],
        )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE prompt_fields SET llm_selection_mode = 'fixed' "
            "WHERE llm_configuration_id IS NOT NULL"
        )
    )

    with op.batch_alter_table("llm_configurations") as batch:
        batch.add_column(
            sa.Column(
                "selection_role",
                sa.String(length=16),
                nullable=False,
                server_default="balanced",
            )
        )
        batch.add_column(
            sa.Column(
                "capability_vision",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "capability_tools",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "capability_structured_output",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "capability_long_context",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "enabled_for_auto",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=False,
                server_default="100",
            )
        )

    conn.execute(
        sa.text(
            "UPDATE llm_configurations SET selection_role = 'fast', "
            "capability_vision = :vision, capability_long_context = :long_context "
            "WHERE profile_id IN ('deepseek-flash', 'qwen-3.8-27b')"
        ),
        {"vision": True, "long_context": False},
    )
    conn.execute(
        sa.text(
            "UPDATE llm_configurations SET capability_long_context = :long_context "
            "WHERE profile_id = 'deepseek-flash'"
        ),
        {"long_context": True},
    )
    conn.execute(
        sa.text(
            "UPDATE llm_configurations SET selection_role = 'deep', "
            "capability_long_context = :long_context "
            "WHERE profile_id = 'deepseek-v4-pro'"
        ),
        {"long_context": True},
    )
    conn.execute(
        sa.text(
            "UPDATE llm_configurations SET selection_role = 'balanced' "
            "WHERE profile_id = 'gpt-oss-120b'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("llm_configurations") as batch:
        batch.drop_column("priority")
        batch.drop_column("enabled_for_auto")
        batch.drop_column("capability_long_context")
        batch.drop_column("capability_structured_output")
        batch.drop_column("capability_tools")
        batch.drop_column("capability_vision")
        batch.drop_column("selection_role")

    with op.batch_alter_table("prompt_fields") as batch:
        batch.drop_index("ix_prompt_fields_llm_selection_mode")
        batch.drop_column("llm_selection_mode")
