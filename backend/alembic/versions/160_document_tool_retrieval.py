"""Sharpen document-tool descriptions and add Jev relevance prompts.

Revision ID: 160_document_tool_retrieval
Revises: 159_workspace_open_without_asking
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision = "160_document_tool_retrieval"
down_revision = "159_workspace_open_without_asking"
branch_labels = None
depends_on = None

_NEW_KEYS = ("chat.expert.tool_relevance", "chat.expert.tool_relevance_rank")
_OLD = {
    "workspace.voice.tool.get_workspace_context": {
        "sv": "Läs sparad vy, markering, källor, aktiv artefakt och available_documents: aktuell inventering av behöriga filer i företagets och aktiva klientens workspace, även utan koppling till dialogytan. Filnamn och status är data, ingen dokumentevidens.",
        "en": "Read saved view, selection, sources, active artifact and available_documents: the current inventory of authorized company and active-client files, even without attachment to the dialogue canvas. Filenames and status are data, not documentary evidence.",
    },
    "workspace.voice.tool.search_knowledge": {
        "sv": "Sök i dokumentens text, inte bara i filnamn, efter det användaren frågar om. Använd den när användaren vill öppna eller hitta ett avtal efter en part, ett bolag eller ett ämne som inte står i filnamnet. Skicka query med användarens egna ord. Öppna sedan träffens source_id med show_document. Detta läser dokumenten; search_companies gör det inte.",
        "en": "Search the text of the user's documents, not only filenames, for what they asked. Use it when the user wants to open or find a contract by a party, company or subject that is not in the filename. Send query in the user's own words. Then open the hit's source_id with show_document. This reads the documents; search_companies does not.",
    },
    "workspace.voice.tool.read_source": {
        "sv": "Läs texten i ett dokument. Skicka source_id från available_documents eller open_documents. Använd när användaren vill att du läser ett avtal och hittar en part. Svara först när texten har kommit tillbaka.",
        "en": "Read the text of one document. Send source_id from available_documents or open_documents. Use this when the user wants you to read a contract and find a party. Answer only after the text comes back.",
    },
    "workspace.voice.tool.show_document": {
        "sv": "Öppna dokumentet i vyn. Om filnamnet innehåller det användaren nämner, skicka den source_id direkt. Om namnet inte står i något filnamn, anropa först search_knowledge och öppna träffens source_id. Bekräfta först när dokumentet syns.",
        "en": "Open the document in the view. If a filename contains what the user named, send that source_id immediately. If the name is not in any filename, call search_knowledge first and open the hit's source_id. Confirm only once the document is visible.",
    },
    "workspace.voice.tool.focus_anchor": {
        "sv": "Markera exakta ord i dokumentvyn. Skicka source_id från open_documents och quote med orden som ska markeras, till exempel kundens namn. Bekräfta först när markeringen syns.",
        "en": "Highlight exact words in the document view. Send source_id from open_documents and quote with the words to mark, such as the customer name. Confirm only once the highlight is visible.",
    },
}
for _texts in _OLD.values():
    _texts["nb"] = _texts["sv"]


def _catalog(key: str) -> dict[str, str]:
    for field in PROMPT_FIELDS:
        if field["key"] == key:
            return field["defaults"]
    raise RuntimeError(f"missing prompt catalog field {key}")


def _apply(key: str, language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(f"UPDATE prompt_fields SET {column} = :new WHERE key = :key AND {column} = :old"),
        {"key": key, "old": old, "new": new},
    )
    connection.execute(
        sa.text(
            "UPDATE prompt_overrides SET text = :new WHERE language = :language AND text = :old "
            "AND prompt_field_id = (SELECT id FROM prompt_fields WHERE key = :key)"
        ),
        {"key": key, "language": language, "old": old, "new": new},
    )


def _insert(key: str) -> None:
    connection = op.get_bind()
    exists = connection.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=key)
    ).fetchone()
    if exists is not None:
        return
    field = next(row for row in PROMPT_FIELDS if row["key"] == key)
    labels = field["label"]
    hints = field["hint"]
    defaults = field["defaults"]
    connection.execute(
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


def upgrade() -> None:
    for key in _NEW_KEYS:
        _insert(key)
    for key, previous in _OLD.items():
        current = _catalog(key)
        for language in ("sv", "en", "nb"):
            _apply(key, language, previous[language], current[language])


def downgrade() -> None:
    connection = op.get_bind()
    for key, previous in _OLD.items():
        current = _catalog(key)
        for language in ("sv", "en", "nb"):
            _apply(key, language, current[language], previous[language])
    for key in _NEW_KEYS:
        field_id = connection.execute(
            sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=key)
        ).fetchone()
        if field_id is None:
            continue
        connection.execute(
            sa.text("DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id").bindparams(
                field_id=field_id[0]
            )
        )
        connection.execute(sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(key=key))
