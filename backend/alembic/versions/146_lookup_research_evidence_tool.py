"""Add lookup_research_evidence and its chat prompt.

Revision ID: 146_lookup_research_evidence_tool
Revises: 145_drop_lookup_frozen_evidence_tool
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "146_lookup_research_evidence_tool"
down_revision: str | Sequence[str] | None = "145_drop_lookup_frozen_evidence_tool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "chat.expert.evidence_tool"
_TOOL = "lookup_research_evidence"
_personas = sa.table(
    "personas",
    sa.column("id", sa.String()),
    sa.column("kind", sa.String()),
    sa.column("tools", sa.JSON()),
)


def _field() -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == _KEY)


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_KEY)
    ).fetchone()
    if exists is None:
        field = _field()
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
                key=_KEY,
                modules=modules_for_prompt_key(_KEY),
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
    rows = conn.execute(
        sa.select(_personas.c.id, _personas.c.kind, _personas.c.tools)
    )
    for persona_id, kind, raw_tools in rows:
        if kind != "expert" or not isinstance(raw_tools, list) or not raw_tools:
            continue
        if _TOOL in raw_tools:
            continue
        conn.execute(
            _personas.update()
            .where(_personas.c.id == persona_id)
            .values(tools=[*raw_tools, _TOOL])
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.select(_personas.c.id, _personas.c.tools))
    for persona_id, raw_tools in rows:
        tools = list(raw_tools or [])
        if _TOOL not in tools:
            continue
        conn.execute(
            _personas.update()
            .where(_personas.c.id == persona_id)
            .values(tools=[name for name in tools if name != _TOOL])
        )
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_KEY)
    ).fetchone()
    if field_id is None:
        return
    conn.execute(
        sa.text("DELETE FROM prompt_overrides WHERE prompt_field_id = :id").bindparams(
            id=field_id[0]
        )
    )
    conn.execute(
        sa.text("DELETE FROM prompt_fields WHERE id = :id").bindparams(id=field_id[0])
    )
