"""Tell the voice agent to search document text before asking which file."""

import sqlalchemy as sa
from alembic import op

from app.services.workspace_prompt_defaults import workspace_prompt_fields

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
        "anropa show_document i samma tur med den source_id. När användaren vill se en dokumenttyp eller en mängd "
        "dokument (till exempel alla hyresavtal), anropa find_documents med query satt till en kompakt sökterm för "
        "dokumenttypen eller ämnet (till exempel \"anställningsavtal\") — inte en hel mening och inte användarens "
        "ordagranna formulering. Använd mode=filter eller within när hen filtrerar det aktiva document_set, och "
        "mode=extend när hen vill lägga till fler. När find_documents returnerar source_ids: anropa show_document_set "
        "med title och presentation_source_ids (eller source_ids om presentation_truncated är false). Sökresultatets "
        "source_ids och document_count är alltid hela mängden; galleriet kan visa ett urval. Om användaren nämner en "
        "part, ett bolag eller en plats i texten, anropa search_knowledge. Filnamn visar inte att innehållet saknas. "
        "När sökningen ger träff i ett dokument, anropa show_document med träffens source_id. Fråga inte vilken fil "
        "när användaren har bett att få se sökresultatet. Fråga inte om du ska öppna det, och säg inte att filen finns "
        "men inte är öppen. Bekräfta först när klientverktyget har svarat completed.",
        "När användaren ber dig öppna ett dokument eller avtal, anropa show_document i samma tur med source_id från "
        "available_documents. Fråga inte om du ska öppna det, och säg inte att filen finns men inte är öppen. "
        "Bekräfta först när show_document har svarat completed. Om flera filer kan avses, fråga vilken.",
    ),
    "en": (
        "When the user asks you to open a document or contract and the name appears in a filename in "
        "available_documents, call show_document in the same turn with that source_id. When the user wants a document "
        "type or set (for example all lease agreements), call find_documents with query set to a compact search term "
        "for the document type or subject (for example \"employment agreements\") — not a full sentence and not the "
        "user's verbatim wording. Use mode=filter or within when they filter the active document_set, and mode=extend "
        "when they want to add more. When find_documents returns source_ids, call show_document_set with title and "
        "presentation_source_ids (or source_ids when presentation_truncated is false). The search result source_ids and "
        "document_count are always the full set; the gallery may show a subset. If the user names a party, company or "
        "place in the text, call search_knowledge. Filenames do not show that the content is missing. When the search "
        "hits one document, call show_document with that hit's source_id. Do not ask which file when the user asked to "
        "see the search result. Do not ask whether to open it, and do not say the file is available but not open. "
        "Confirm only after the client tool returns completed.",
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


def _make_field(
    key: str,
    _section: str,
    _label_sv: str,
    _label_en: str,
    _hint_sv: str,
    _hint_en: str,
    default_sv: str,
    default_en: str,
) -> dict:
    return {"key": key, "defaults": {"sv": default_sv, "en": default_en, "nb": default_sv}}


def _catalog(key: str) -> dict[str, str]:
    # Pre-split legacy texts: 180 applies the compact overrides, not this migration.
    for field in workspace_prompt_fields(_make_field, apply_overrides=False):
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
