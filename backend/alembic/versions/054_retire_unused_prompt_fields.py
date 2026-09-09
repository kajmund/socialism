"""Remove unused prompt catalog keys and leftover overrides.

Revision ID: 054_retire_unused_prompt_fields
Revises: 053_word_rewrite_suggestion

persona.from_slot.* is no longer used (slot profiles are built from recipe fields).
help.system.scb_population is covered by help.system.scb.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "054_retire_unused_prompt_fields"
down_revision: Union[str, Sequence[str], None] = "053_word_rewrite_suggestion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETIRED_KEYS = (
    "persona.from_slot.system",
    "persona.from_slot.user",
    "help.system.scb_population",
)


def upgrade() -> None:
    conn = op.get_bind()
    prompt_fields = sa.table(
        "prompt_fields",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
    )
    prompt_overrides = sa.table(
        "prompt_overrides",
        sa.column("prompt_field_id", sa.Integer),
    )
    configurations = sa.table(
        "configurations",
        sa.column("id", sa.Integer),
        sa.column("prompts", sa.JSON),
        sa.column("updated_at", sa.DateTime),
    )

    field_ids = [
        row[0]
        for row in conn.execute(
            sa.select(prompt_fields.c.id).where(prompt_fields.c.key.in_(_RETIRED_KEYS))
        )
    ]
    if field_ids:
        conn.execute(
            prompt_overrides.delete().where(
                prompt_overrides.c.prompt_field_id.in_(field_ids)
            )
        )
        conn.execute(prompt_fields.delete().where(prompt_fields.c.id.in_(field_ids)))

    retired = set(_RETIRED_KEYS)
    now = datetime.now(timezone.utc)
    for row_id, raw in conn.execute(
        sa.select(configurations.c.id, configurations.c.prompts)
    ):
        stored = raw
        if isinstance(stored, str):
            stored = json.loads(stored)
        if not isinstance(stored, dict) or not any(key in stored for key in retired):
            continue
        cleaned = {key: value for key, value in stored.items() if key not in retired}
        conn.execute(
            configurations.update()
            .where(configurations.c.id == row_id)
            .values(prompts=cleaned, updated_at=now)
        )


def downgrade() -> None:
    pass
