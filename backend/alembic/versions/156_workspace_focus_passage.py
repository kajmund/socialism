"""Tell the voice agent to highlight a quote in the document view."""

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision = "156_workspace_focus_passage"
down_revision = "155_workspace_document_answer"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_PARAGRAPHS = {
    "sv": "Du markerar i dokumentvyn genom att anropa focus_anchor med source_id från open_documents och quote "
    "med de exakta orden, till exempel kundens namn. Säg aldrig att du inte kan markera eller visa platsen. "
    "Bekräfta markeringen först när focus_anchor har svarat completed. Om användaren säger att ingen markering "
    "syns, anropa focus_anchor direkt.",
    "en": "You highlight in the document view by calling focus_anchor with source_id from open_documents and "
    "quote set to the exact words, such as the customer name. Never say you cannot mark or show the place. "
    "Confirm the highlight only after focus_anchor returns completed. If the user says no highlight is visible, "
    "call focus_anchor immediately.",
}
_PARAGRAPHS["nb"] = _PARAGRAPHS["sv"]

_TOOL = "workspace.voice.tool.focus_anchor"
_TOOL_OLD = {
    "sv": "Markera verifierat dokumentankare. Bekräfta endast när rätt sida och markering visas.",
    "en": "Highlight a verified document anchor. Confirm only once the correct page and highlight are visible.",
    "nb": "Markera verifierat dokumentankare. Bekräfta endast när rätt sida och markering visas.",
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
        raise RuntimeError("focus passage paragraph missing from workspace.voice.system")
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
