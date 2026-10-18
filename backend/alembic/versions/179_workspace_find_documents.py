"""Wire find_documents into workspace prompts for OverGraph document sets."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "179_workspace_find_documents"
down_revision: str | Sequence[str] | None = "178_workspace_document_sets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "workspace.voice.tool.find_documents"
_REPLACEMENTS = (
    (
        "workspace.voice.system",
        "När användaren ber dig öppna ett dokument eller avtal och namnet står i ett filnamn i "
        "available_documents, anropa show_document i samma tur med den source_id. Om användaren nämner "
        "en part, ett bolag eller ett ämne som inte står i något filnamn, anropa search_knowledge med "
        "de orden innan du svarar. Filnamn visar inte att innehållet saknas. När sökningen ger träff i "
        "ett dokument, anropa show_document med träffens source_id. När sökningen ger träffar i flera "
        "dokument, anropa show_document_set med en kort rubrik som beskriver sökningen och dokumentens "
        "unika source_id. Fråga inte vilken fil när användaren har bett att få se sökresultatet.",
        "När användaren ber dig öppna ett dokument eller avtal och namnet står i ett filnamn i "
        "available_documents, anropa show_document i samma tur med den source_id. När användaren vill se "
        "en dokumenttyp eller en mängd dokument (till exempel alla hyresavtal), anropa find_documents "
        "med query. Använd mode=filter eller within när hen filtrerar det aktiva document_set, och "
        "mode=extend när hen vill lägga till fler. När find_documents returnerar source_ids: anropa "
        "show_document_set med title och presentation_source_ids (eller source_ids om "
        "presentation_truncated är false). Sökresultatets source_ids och document_count är alltid hela "
        "mängden; galleriet kan visa ett urval. Om användaren nämner en part, ett bolag eller en plats "
        "i texten, anropa search_knowledge. Filnamn visar inte att innehållet saknas. När sökningen ger "
        "träff i ett dokument, anropa show_document med träffens source_id. Fråga inte vilken fil när "
        "användaren har bett att få se sökresultatet.",
        "When the user asks you to open a document or contract and the name appears in a filename in "
        "available_documents, call show_document in the same turn with that source_id. If the user names "
        "a party, company or subject that is not in any filename, call search_knowledge with those words "
        "before you answer. Filenames do not show that the content is missing. When the search hits one "
        "document, call show_document with that hit's source_id. When it hits several documents, call "
        "show_document_set with a short title describing the search and the documents' unique source_id "
        "values. Do not ask which file when the user asked to see the search result.",
        "When the user asks you to open a document or contract and the name appears in a filename in "
        "available_documents, call show_document in the same turn with that source_id. When the user wants "
        "a document type or set (for example all lease agreements), call find_documents with query. Use "
        "mode=filter or within when they filter the active document_set, and mode=extend when they want "
        "to add more. When find_documents returns source_ids, call show_document_set with title and "
        "presentation_source_ids (or source_ids when presentation_truncated is false). The search result "
        "source_ids and document_count are always the full set; the gallery may show a subset. If the "
        "user names a party, company or place in the text, call search_knowledge. Filenames do not show "
        "that the content is missing. When the search hits one document, call show_document with that "
        "hit's source_id. Do not ask which file when the user asked to see the search result.",
    ),
    (
        "workspace.chat.turn",
        "Saknar du source_id, anropa search_knowledge med användarens egna ord. När underlaget innehåller "
        "ett source_id, anropa show_document med det i samma svar. När sökresultatet innehåller flera "
        "dokument som användaren vill se, anropa show_document_set med en kort sökrubrik och dokumentens "
        "source_id. En mening utan visningsanropet öppnar inget.",
        "Saknar du source_id för en dokumentmängd, anropa find_documents med användarens egna ord. När "
        "find_documents returnerar flera source_ids, anropa show_document_set med title och "
        "presentation_source_ids. source_ids i svaret är alltid hela mängden. För platser i texten, "
        "anropa search_knowledge. När underlaget innehåller ett source_id, anropa show_document med det "
        "i samma svar. En mening utan visningsanropet öppnar inget.",
        "If you lack source_id, call search_knowledge with the user's own words. When the material "
        "contains one source_id, call show_document with it in the same reply. When the search result "
        "contains several documents the user wants to see, call show_document_set with a short search "
        "title and the documents' source_id values. A sentence without the display call opens nothing.",
        "If you lack source_id for a document set, call find_documents with the user's own words. When "
        "find_documents returns several source_ids, call show_document_set with title and "
        "presentation_source_ids. source_ids in the result are always the full set. For places in the "
        "text, call search_knowledge. When the material contains one source_id, call show_document with "
        "it in the same reply. A sentence without the display call opens nothing.",
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
    field = connection.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key"), {"key": _KEY},
    ).fetchone()
    if field:
        connection.execute(
            sa.text("DELETE FROM prompt_overrides WHERE prompt_field_id = :id"), {"id": field[0]},
        )
        connection.execute(sa.text("DELETE FROM prompt_fields WHERE id = :id"), {"id": field[0]})
