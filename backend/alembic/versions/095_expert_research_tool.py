"""Give existing expert personas the background-research tool.

Revision ID: 095_expert_research_tool
Revises: 094_research_question_attempt
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "095_expert_research_tool"
down_revision: str | Sequence[str] | None = "094_research_question_attempt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOOL = "start_research"
_personas = sa.table(
    "personas",
    sa.column("id", sa.String()),
    sa.column("kind", sa.String()),
    sa.column("tools", sa.JSON()),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_personas.c.id, _personas.c.tools).where(_personas.c.kind == "expert")
    )
    for persona_id, raw_tools in rows:
        tools = list(raw_tools or [])
        if _TOOL not in tools:
            bind.execute(
                _personas.update()
                .where(_personas.c.id == persona_id)
                .values(tools=[*tools, _TOOL])
            )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_personas.c.id, _personas.c.tools).where(_personas.c.kind == "expert")
    )
    for persona_id, raw_tools in rows:
        tools = [tool for tool in list(raw_tools or []) if tool != _TOOL]
        bind.execute(
            _personas.update().where(_personas.c.id == persona_id).values(tools=tools)
        )
