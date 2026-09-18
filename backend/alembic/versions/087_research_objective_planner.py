"""Attempt research objective snapshot and initial planner prompts.

Revision ID: 087_research_objective_planner
Revises: 086_runtime_need_routing_constraints
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "087_research_objective_planner"
down_revision: Union[str, Sequence[str], None] = "086_runtime_need_routing_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_KEYS = (
    "research.planner.system",
    "research.planner.user",
)


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def upgrade() -> None:
    op.add_column(
        "execution_attempts",
        sa.Column("research_objective_snapshot", sa.JSON(), nullable=True),
    )
    conn = op.get_bind()
    for key in _NEW_KEYS:
        exists = conn.execute(
            sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=key)
        ).fetchone()
        if exists is not None:
            continue
        field = _field(key)
        labels = field["label"]
        hints = field["hint"]
        defaults = field["defaults"]
        conn.execute(
            sa.text(
                "INSERT INTO prompt_fields ("
                "key, modules, section, label_sv, label_en, hint_sv, hint_en, "
                "default_sv, default_en, default_nb, active"
                ") VALUES ("
                ":key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
                ":default_sv, :default_en, :default_nb, TRUE"
                ")"
            ).bindparams(
                sa.bindparam("modules", type_=sa.JSON()),
                key=key,
                modules=modules_for_prompt_key(key),
                section=field["section"],
                label_sv=labels["sv"],
                label_en=labels["en"],
                hint_sv=hints["sv"],
                hint_en=hints["en"],
                default_sv=defaults["sv"],
                default_en=defaults["en"],
                default_nb=defaults["nb"],
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key in _NEW_KEYS:
        field_id = conn.execute(
            sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=key)
        ).fetchone()
        if field_id is None:
            continue
        conn.execute(
            sa.text(
                "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
            ).bindparams(field_id=field_id[0])
        )
        conn.execute(
            sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(key=key)
        )
    op.drop_column("execution_attempts", "research_objective_snapshot")
