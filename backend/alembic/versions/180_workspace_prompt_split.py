"""Split workspace instructions into system, tool and Jev-selected task prompts."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key
from app.services.workspace_prompt_defaults import workspace_prompt_fields

revision: str = "180_workspace_prompt_split"
down_revision: str | Sequence[str] | None = "179_workspace_find_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASK_KEYS = (
    "workspace.voice.task.document_find",
    "workspace.voice.task.document_locate",
    "workspace.voice.task.document_mark",
)
_UPDATED_KEYS = (
    "workspace.voice.system",
    "workspace.chat.turn",
    "workspace.voice.tool.find_documents",
    "workspace.voice.tool.search_knowledge",
    "workspace.voice.tool.read_source",
    "workspace.voice.tool.show_document",
    "workspace.voice.tool.show_document_set",
    "workspace.voice.tool.focus_anchor",
)


def _make_field(
    key: str,
    section: str,
    _label_sv: str,
    _label_en: str,
    _hint_sv: str,
    _hint_en: str,
    default_sv: str,
    default_en: str,
) -> dict:
    return {"key": key, "section": section, "sv": default_sv, "en": default_en}


def _texts(*, legacy: bool) -> dict[str, dict]:
    rows = workspace_prompt_fields(_make_field, apply_overrides=not legacy)
    return {row["key"]: row for row in rows}


def _catalog_field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def _insert_task_fields() -> None:
    connection = op.get_bind()
    for key in _TASK_KEYS:
        if connection.execute(
            sa.text("SELECT id FROM prompt_fields WHERE key = :key"), {"key": key}
        ).fetchone():
            continue
        field = _catalog_field(key)
        connection.execute(
            sa.text(
                "INSERT INTO prompt_fields "
                "(key, modules, section, label_sv, label_en, hint_sv, hint_en, "
                "default_sv, default_en, default_nb, active) VALUES "
                "(:key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
                ":default_sv, :default_en, :default_nb, TRUE)"
            ).bindparams(sa.bindparam("modules", type_=sa.JSON())),
            {
                "key": key,
                "modules": modules_for_prompt_key(key),
                "section": field["section"],
                "label_sv": field["label"]["sv"],
                "label_en": field["label"]["en"],
                "hint_sv": field["hint"]["sv"],
                "hint_en": field["hint"]["en"],
                "default_sv": field["defaults"]["sv"],
                "default_en": field["defaults"]["en"],
                "default_nb": field["defaults"]["nb"],
            },
        )


def _replace_prompts(source: dict[str, dict], target: dict[str, dict]) -> None:
    connection = op.get_bind()
    for key in _UPDATED_KEYS:
        for language, source_language in (("sv", "sv"), ("en", "en"), ("nb", "sv")):
            old = source[key][source_language]
            new = target[key][source_language]
            connection.execute(
                sa.text(
                    f"UPDATE prompt_fields SET default_{language} = :new WHERE key = :key"
                ),
                {"key": key, "new": new},
            )
            connection.execute(
                sa.text(
                    "UPDATE prompt_overrides SET text = :new "
                    "WHERE language = :language AND text = :old AND prompt_field_id = "
                    "(SELECT id FROM prompt_fields WHERE key = :key)"
                ),
                {
                    "key": key,
                    "language": language,
                    "old": old,
                    "new": new,
                },
            )


def upgrade() -> None:
    _insert_task_fields()
    _replace_prompts(_texts(legacy=True), _texts(legacy=False))


def downgrade() -> None:
    _replace_prompts(_texts(legacy=False), _texts(legacy=True))
    connection = op.get_bind()
    for key in _TASK_KEYS:
        row = connection.execute(
            sa.text("SELECT id FROM prompt_fields WHERE key = :key"), {"key": key}
        ).fetchone()
        if row:
            connection.execute(
                sa.text("DELETE FROM prompt_overrides WHERE prompt_field_id = :id"),
                {"id": row[0]},
            )
            connection.execute(
                sa.text("DELETE FROM prompt_fields WHERE id = :id"), {"id": row[0]}
            )
