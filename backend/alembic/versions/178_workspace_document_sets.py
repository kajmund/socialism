"""Let experts present multi-document search results as a gallery."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "178_workspace_document_sets"
down_revision: str | Sequence[str] | None = "177_workspace_source_content_sha256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "workspace.voice.tool.show_document_set"
_REPLACEMENTS = (
    (
        "workspace.voice.system",
        "När sökningen ger träffar i ett dokument, anropa show_document med träffens source_id. "
        "Fråga vilken fil bara om sökningen träffar flera olika dokument.",
        "När sökningen ger träff i ett dokument, anropa show_document med träffens source_id. "
        "När sökningen ger träffar i flera dokument, anropa show_document_set med en kort rubrik som "
        "beskriver sökningen och dokumentens unika source_id. Fråga inte vilken fil när användaren har "
        "bett att få se sökresultatet.",
        "When the search hits one document, call show_document with that hit's source_id. "
        "Ask which file only when the search hits several different documents.",
        "When the search hits one document, call show_document with that hit's source_id. When it hits "
        "several documents, call show_document_set with a short title describing the search and the "
        "documents' unique source_id values. Do not ask which file when the user asked to see the search result.",
    ),
    (
        "workspace.chat.turn",
        "När underlaget innehåller source_id för dokumentet, anropa show_document med den i samma svar. "
        "En mening utan det anropet öppnar inget.",
        "När underlaget innehåller ett source_id, anropa show_document med det i samma svar. När sökresultatet "
        "innehåller flera dokument som användaren vill se, anropa show_document_set med en kort sökrubrik och "
        "dokumentens source_id. En mening utan visningsanropet öppnar inget.",
        "When the material contains source_id for that document, call show_document with it in the same reply. "
        "A sentence without that call opens nothing.",
        "When the material contains one source_id, call show_document with it in the same reply. When the search "
        "result contains several documents the user wants to see, call show_document_set with a short search title "
        "and the documents' source_id values. A sentence without the display call opens nothing.",
    ),
)


def _field() -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == _KEY)


def _replace(key: str, language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) WHERE key = :key"),
        {"key": key, "old": old, "new": new},
    )
    connection.execute(
        sa.text(
            "UPDATE prompt_overrides SET text = replace(text, :old, :new) "
            "WHERE language = :language AND prompt_field_id = "
            "(SELECT id FROM prompt_fields WHERE key = :key)"
        ),
        {"key": key, "language": language, "old": old, "new": new},
    )


def _insert_field() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT id FROM prompt_fields WHERE key = :key"), {"key": _KEY}).fetchone():
        return
    field = _field()
    connection.execute(
        sa.text(
            "INSERT INTO prompt_fields (key, modules, section, label_sv, label_en, hint_sv, hint_en, "
            "default_sv, default_en, default_nb, active) VALUES "
            "(:key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
            ":default_sv, :default_en, :default_nb, TRUE)"
        ).bindparams(sa.bindparam("modules", type_=sa.JSON())),
        {
            "key": _KEY,
            "modules": modules_for_prompt_key(_KEY),
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


def upgrade() -> None:
    _insert_field()
    for key, old_sv, new_sv, old_en, new_en in _REPLACEMENTS:
        for language, old, new in (
            ("sv", old_sv, new_sv), ("nb", old_sv, new_sv), ("en", old_en, new_en),
        ):
            _replace(key, language, old, new)


def downgrade() -> None:
    for key, old_sv, new_sv, old_en, new_en in reversed(_REPLACEMENTS):
        for language, old, new in (
            ("sv", new_sv, old_sv), ("nb", new_sv, old_sv), ("en", new_en, old_en),
        ):
            _replace(key, language, old, new)
    connection = op.get_bind()
    field = connection.execute(sa.text("SELECT id FROM prompt_fields WHERE key = :key"), {"key": _KEY}).fetchone()
    if field:
        connection.execute(sa.text("DELETE FROM prompt_overrides WHERE prompt_field_id = :id"), {"id": field[0]})
        connection.execute(sa.text("DELETE FROM prompt_fields WHERE id = :id"), {"id": field[0]})
