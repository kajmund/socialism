"""Named LLM configurations and per-prompt assignment.

Revision ID: 112_llm_configurations
Revises: 111_raw_domain_claims
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "112_llm_configurations"
down_revision: Union[str, Sequence[str], None] = "111_raw_domain_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_configurations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
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
        sa.UniqueConstraint("name", name="uq_llm_configurations_name"),
    )

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("ALTER TABLE llm_configurations ENABLE ROW LEVEL SECURITY")
    row = conn.execute(
        sa.text(
            "SELECT profile_id, temperature, top_p, max_tokens, reasoning_effort "
            "FROM llm_runtime_settings WHERE id = 1"
        )
    ).fetchone()
    if row is not None:
        conn.execute(
            sa.text(
                "INSERT INTO llm_configurations ("
                "name, profile_id, temperature, top_p, max_tokens, "
                "reasoning_effort, is_default"
                ") VALUES ("
                "'Standard', :profile_id, :temperature, :top_p, :max_tokens, "
                ":reasoning_effort, :is_default"
                ")"
            ),
            {
                "profile_id": row[0],
                "temperature": row[1],
                "top_p": row[2],
                "max_tokens": row[3],
                "reasoning_effort": row[4],
                "is_default": True,
            },
        )

    with op.batch_alter_table("prompt_fields") as batch:
        batch.add_column(
            sa.Column("llm_configuration_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_prompt_fields_llm_configuration_id",
            "llm_configurations",
            ["llm_configuration_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_prompt_fields_llm_configuration_id",
            ["llm_configuration_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("prompt_fields") as batch:
        batch.drop_index("ix_prompt_fields_llm_configuration_id")
        batch.drop_constraint(
            "fk_prompt_fields_llm_configuration_id", type_="foreignkey"
        )
        batch.drop_column("llm_configuration_id")
    op.drop_table("llm_configurations")
