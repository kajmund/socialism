"""Add the missing reasoning-assessment questions to the stored prompt.

Revision ID: 182_reasoning_assessment_keys
Revises: 181_simple_model_is_gpt_oss
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.expert_chat_prompts import _reasoning_assessment_questions

_SCORE_KEYS = (
    "simple_operation",
    "analysis",
    "multi_step",
    "comparison",
    "synthesis",
    "conflicting_information",
    "decomposable",
    "parallelizable",
)

revision: str = "182_reasoning_assessment_keys"
down_revision: str | Sequence[str] | None = "181_simple_model_is_gpt_oss"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "chat.expert.reasoning_assessment"
_ADDED = ("decomposable", "parallelizable")


def _catalog(language: str) -> dict:
    source = "en" if language == "en" else "sv"
    return json.loads(_reasoning_assessment_questions(source))


def _aligned(raw: str, language: str) -> str:
    catalog = _catalog(language)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        parsed = {}
    aligned = {}
    for key in _SCORE_KEYS:
        value = parsed.get(key)
        aligned[key] = value if isinstance(value, dict) else catalog[key]
    return json.dumps(aligned, ensure_ascii=False)


def _without_added(raw: str) -> str:
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        for key in _ADDED:
            parsed.pop(key, None)
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
            "sv": _aligned(row[1], "sv"),
            "en": _aligned(row[2], "en"),
            "nb": _aligned(row[3], "nb"),
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
            {"id": override_id, "text": _aligned(text, str(language))},
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
            "sv": _without_added(row[1]),
            "en": _without_added(row[2]),
            "nb": _without_added(row[3]),
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
            {"id": override_id, "text": _without_added(text)},
        )
