"""Add case citation intent prompts before direct retrieval.

Revision ID: 117_case_citation_intent
Revises: 116_preparatory_attribution
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "117_case_citation_intent"
down_revision: str | Sequence[str] | None = "116_preparatory_attribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_KEYS = ("research.lagen_nu.citation_intent.system", "research.lagen_nu.citation_intent.user")


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def upgrade() -> None:
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
            sa.text("DELETE FROM prompt_overrides WHERE field_id = :id").bindparams(id=field_id[0])
        )
        conn.execute(sa.text("DELETE FROM prompt_fields WHERE id = :id").bindparams(id=field_id[0]))
