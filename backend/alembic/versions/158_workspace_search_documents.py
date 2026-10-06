"""Tell the voice agent to search document text before asking which file."""

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision = "158_workspace_search_documents"
down_revision = "157_workspace_open_document"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_CLARIFY = {
    "sv": (
        "Om namnet inte står i ett filnamn, sök i dokumenttexten med search_knowledge innan du ber användaren precisera.",
        "Vid flera möjliga filer, be användaren precisera.",
    ),
    "en": (
        "If the name is not in a filename, search the document text with search_knowledge before asking the user to clarify.",
        "If several files could match, ask the user to clarify.",
    ),
}
_OPEN = {
    "sv": (
        "När användaren ber dig öppna ett dokument eller avtal och namnet står i ett filnamn i available_documents, "
        "anropa show_document i samma tur med den source_id. Om användaren nämner en part, ett bolag eller ett ämne "
        "som inte står i något filnamn, anropa search_knowledge med de orden innan du svarar. Filnamn visar inte att "
        "innehållet saknas. När sökningen ger träffar i ett dokument, anropa show_document med träffens source_id. "
        "Fråga vilken fil bara om sökningen träffar flera olika dokument. Fråga inte om du ska öppna det, och säg "
        "inte att filen finns men inte är öppen. Bekräfta först när show_document har svarat completed.",
        "När användaren ber dig öppna ett dokument eller avtal, anropa show_document i samma tur med source_id från "
        "available_documents. Fråga inte om du ska öppna det, och säg inte att filen finns men inte är öppen. "
        "Bekräfta först när show_document har svarat completed. Om flera filer kan avses, fråga vilken.",
    ),
    "en": (
        "When the user asks you to open a document or contract and the name appears in a filename in "
        "available_documents, call show_document in the same turn with that source_id. If the user names a party, "
        "company or subject that is not in any filename, call search_knowledge with those words before you answer. "
        "Filenames do not show that the content is missing. When the search hits one document, call show_document "
        "with that hit's source_id. Ask which file only when the search hits several different documents. Do not "
        "ask whether to open it, and do not say the file is available but not open. Confirm only after "
        "show_document returns completed.",
        "When the user asks you to open a document or contract, call show_document in the same turn with source_id "
        "from available_documents. Do not ask whether to open it, and do not say the file is available but not "
        "open. Confirm only after show_document returns completed. If several files could match, ask which one.",
    ),
}
_CLARIFY["nb"] = _CLARIFY["sv"]
_OPEN["nb"] = _OPEN["sv"]

_TOOLS = {
    "workspace.voice.tool.search_knowledge": {
        "sv": "Sök i användarens dokument efter det hen frågar om, till exempel vilken part som är kund i ett avtal. Skicka query med användarens egna ord. Returnera träffar med referenser. Detta läser dokumenten; search_companies gör det inte.",
        "en": "Search the user's documents for what they asked, such as which party is the customer in a contract. Send query in the user's own words. Return hits with references. This reads the documents; search_companies does not.",
    },
    "workspace.voice.tool.show_document": {
        "sv": "Öppna dokumentet i vyn. Skicka source_id från available_documents. Anropa direkt när användaren ber dig öppna ett avtal. Bekräfta först när dokumentet syns.",
        "en": "Open the document in the view. Send source_id from available_documents. Call it immediately when the user asks you to open a contract. Confirm only once the document is visible.",
    },
}
for _key, _texts in _TOOLS.items():
    _texts["nb"] = _texts["sv"]


def _catalog(key: str) -> dict[str, str]:
    for field in PROMPT_FIELDS:
        if field["key"] == key:
            return field["defaults"]
    raise RuntimeError(f"missing prompt catalog field {key}")


def _previous_system(language: str) -> str:
    current = _catalog(_SYSTEM)[language]
    for new, old in (_CLARIFY[language], _OPEN[language]):
        if new not in current:
            raise RuntimeError("document search paragraph missing from workspace.voice.system")
        current = current.replace(new, old, 1)
    return current


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


def upgrade() -> None:
    for language in ("sv", "en", "nb"):
        _apply(_SYSTEM, language, _previous_system(language), _catalog(_SYSTEM)[language])
        for key, old in _TOOLS.items():
            _apply(key, language, old[language], _catalog(key)[language])


def downgrade() -> None:
    for language in ("sv", "en", "nb"):
        _apply(_SYSTEM, language, _catalog(_SYSTEM)[language], _previous_system(language))
        for key, old in _TOOLS.items():
            _apply(key, language, _catalog(key)[language], old[language])
