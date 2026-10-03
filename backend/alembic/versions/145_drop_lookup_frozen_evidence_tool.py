"""Drop the retired lookup_frozen_evidence tool from stored personas.

Revision ID: 145_drop_lookup_frozen_evidence_tool
Revises: 144_consult_prompt_ignore_fake_sends
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "145_drop_lookup_frozen_evidence_tool"
down_revision: str | Sequence[str] | None = "144_consult_prompt_ignore_fake_sends"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOOL = "lookup_frozen_evidence"
_personas = sa.table(
    "personas",
    sa.column("id", sa.String()),
    sa.column("tools", sa.JSON()),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(_personas.c.id, _personas.c.tools))
    for persona_id, raw_tools in rows:
        tools = list(raw_tools or [])
        if _TOOL not in tools:
            continue
        bind.execute(
            _personas.update()
            .where(_personas.c.id == persona_id)
            .values(tools=[tool for tool in tools if tool != _TOOL])
        )


def downgrade() -> None:
    """The catalog rejects this tool id, so it is not written back."""
