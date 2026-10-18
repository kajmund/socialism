"""Drop tautological noul criteria from the reasoning-assessment prompt.

Revision ID: 183_reasoning_assessment_questions
Revises: 182_reasoning_assessment_keys
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "183_reasoning_assessment_questions"
down_revision: str | Sequence[str] | None = "182_reasoning_assessment_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "chat.expert.reasoning_assessment"
_CRITERIA = {
    "en": {
        "true": "The task matches the criterion.",
        "false": "The task does not match the criterion.",
    },
    "sv": {
        "true": "Uppgiften matchar kriteriet.",
        "false": "Uppgiften matchar inte kriteriet.",
    },
}


def _strip(raw: str) -> str:
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, dict):
                value.pop("criteria", None)
    return json.dumps(parsed, ensure_ascii=False)


def _restore(raw: str, language: str) -> str:
    criteria = _CRITERIA["en"] if language == "en" else _CRITERIA["sv"]
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, dict):
                value["criteria"] = dict(criteria)
    return json.dumps(parsed, ensure_ascii=False)


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT id, default_sv, default_en, default_nb "
            "FROM prompt_fields WHERE key = :key"
        ),
        {"key": _KEY},
    ).fetchone()
    if row is None:
        return
    field_id = row[0]
    conn.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE id = :id"
        ),
        {
            "id": field_id,
            "sv": _strip(row[1]),
            "en": _strip(row[2]),
            "nb": _strip(row[3]),
        },
    )
    overrides = conn.execute(
        sa.text(
            "SELECT id, text FROM prompt_overrides WHERE prompt_field_id = :field_id"
        ),
        {"field_id": field_id},
    ).fetchall()
    for override_id, text in overrides:
        conn.execute(
            sa.text("UPDATE prompt_overrides SET text = :text WHERE id = :id"),
            {"id": override_id, "text": _strip(text)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT id, default_sv, default_en, default_nb "
            "FROM prompt_fields WHERE key = :key"
        ),
        {"key": _KEY},
    ).fetchone()
    if row is None:
        return
    field_id = row[0]
    conn.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE id = :id"
        ),
        {
            "id": field_id,
            "sv": _restore(row[1], "sv"),
            "en": _restore(row[2], "en"),
            "nb": _restore(row[3], "nb"),
        },
    )
    overrides = conn.execute(
        sa.text(
            "SELECT id, language, text FROM prompt_overrides "
            "WHERE prompt_field_id = :field_id"
        ),
        {"field_id": field_id},
    ).fetchall()
    for override_id, language, text in overrides:
        conn.execute(
            sa.text("UPDATE prompt_overrides SET text = :text WHERE id = :id"),
            {"id": override_id, "text": _restore(text, str(language))},
        )
