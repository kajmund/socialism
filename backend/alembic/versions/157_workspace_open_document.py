"""Tell the voice agent to open a named document instead of asking permission."""

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision = "157_workspace_open_document"
down_revision = "156_workspace_focus_passage"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_PARAGRAPHS = {
    "sv": "När användaren ber dig öppna ett dokument eller avtal, anropa show_document i samma tur med "
    "source_id från available_documents. Fråga inte om du ska öppna det, och säg inte att filen finns men "
    "inte är öppen. Bekräfta först när show_document har svarat completed. Om flera filer kan avses, fråga vilken.",
    "en": "When the user asks you to open a document or contract, call show_document in the same turn with "
    "source_id from available_documents. Do not ask whether to open it, and do not say the file is available "
    "but not open. Confirm only after show_document returns completed. If several files could match, ask which one.",
}
_PARAGRAPHS["nb"] = _PARAGRAPHS["sv"]

_TOOL = "workspace.voice.tool.show_document"
_TOOL_OLD = {
    "sv": "Öppna behöriga source_id eller reference_id med exakt ankare. Vänta på bekräftad visning.",
    "en": "Open authorized source_id or reference_id with an exact anchor. Wait for confirmed display.",
    "nb": "Öppna behöriga source_id eller reference_id med exakt ankare. Vänta på bekräftad visning.",
}


def _catalog(key: str) -> dict[str, str]:
    for field in PROMPT_FIELDS:
        if field["key"] == key:
            return field["defaults"]
    raise RuntimeError(f"missing prompt catalog field {key}")


def _previous_system(language: str) -> str:
    paragraph = _PARAGRAPHS[language] + "\n"
    current = _catalog(_SYSTEM)[language]
    if paragraph not in current:
        raise RuntimeError("open document paragraph missing from workspace.voice.system")
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
        _apply(_TOOL, language, _TOOL_OLD[language], _catalog(_TOOL)[language])


def downgrade() -> None:
    for language in ("sv", "en", "nb"):
        _apply(_SYSTEM, language, _catalog(_SYSTEM)[language], _previous_system(language))
        _apply(_TOOL, language, _catalog(_TOOL)[language], _TOOL_OLD[language])
