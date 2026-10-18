"""Tell the voice agent to answer from the open document instead of narrating a search."""

import sqlalchemy as sa
from alembic import op

from app.services.workspace_prompt_defaults import workspace_prompt_fields

revision = "155_workspace_document_answer"
down_revision = "154_workspace_chat_turn_prompt"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_PARAGRAPHS = {
    "sv": "Dokument som visas i kontexten är texten för de dokument som ligger framme, för alla experter. "
    "När användaren ber dig läsa ett avtal eller hitta en part: svara i samma tur utifrån den texten och namnge "
    "parten hen menar. Säg inte att du letar, läser eller återkommer, och fråga inte om användaren är kvar, "
    "förrän svaret finns. search_companies slår upp bolag i ett register och läser inte avtalet. Om svaret "
    "saknas i Dokument som visas, anropa read_source med source_id eller search_knowledge med query och tala först "
    "när verktyget har returnerat text.",
    "en": "The documents on screen in the context are the text of what is already open, for every expert. "
    "When the user asks you to read a contract or find a party, answer in the same turn from that text and "
    "name the party they mean. Do not say you are searching, reading or will come back, and do not ask if the "
    "user is still there, before you have the answer. search_companies looks up companies in a registry and "
    "does not read the contract. If the answer is not in the documents on screen, call read_source with source_id or "
    "search_knowledge with query and speak only after the tool returns the text.",
}
_PARAGRAPHS["nb"] = _PARAGRAPHS["sv"]

_TOOL_OLD = {
    "workspace.voice.tool.search_knowledge": {
        "sv": "Sök endast inom valt kunskapsområde. Returnera stabila källreferenser; minnen är aldrig evidens.",
        "en": "Search only the selected knowledge scope. Return stable source references; memories are never evidence.",
        "nb": "Sök endast inom valt kunskapsområde. Returnera stabila källreferenser; minnen är aldrig evidens.",
    },
    "workspace.voice.tool.read_source": {
        "sv": "Läs behörig källa eller källreferens med exakt dokumentankare.",
        "en": "Read an authorized source or reference with its exact document anchor.",
        "nb": "Läs behörig källa eller källreferens med exakt dokumentankare.",
    },
}


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
    paragraph = _PARAGRAPHS[language] + "\n"
    current = _catalog(_SYSTEM)[language]
    if paragraph not in current:
        raise RuntimeError("document answer paragraph missing from workspace.voice.system")
    return current.replace(paragraph, "", 1)


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
        for key, old in _TOOL_OLD.items():
            _apply(key, language, old[language], _catalog(key)[language])


def downgrade() -> None:
    for language in ("sv", "en", "nb"):
        _apply(_SYSTEM, language, _catalog(_SYSTEM)[language], _previous_system(language))
        for key, old in _TOOL_OLD.items():
            _apply(key, language, _catalog(key)[language], old[language])
