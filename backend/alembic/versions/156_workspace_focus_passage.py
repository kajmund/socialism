"""Tell the voice agent to highlight a quote in the document view."""

import sqlalchemy as sa
from alembic import op

from app.services.workspace_prompt_defaults import workspace_prompt_fields

revision = "156_workspace_focus_passage"
down_revision = "155_workspace_document_answer"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_PARAGRAPHS = {
    "sv": "Du markerar i dokumentvyn genom att anropa focus_anchor en gång per passage, med source_id "
    "från open_documents och quote med just den passagens exakta ord. Flera anrop på samma dokument "
    "markerar flera passager. Säg aldrig att du inte kan markera eller visa platsen. Bekräfta varje "
    "passage först när dess focus_anchor har svarat completed. Säg inte att en passage är markerad om "
    "du inte anropat focus_anchor för den. Om användaren säger att ingen markering syns, anropa "
    "focus_anchor direkt. När du har en kommentar till passagen skickar du den i comment i samma "
    "anrop. Kommentaren visas vid markeringen i ditt namn. Utelämna comment när passagen bara ska "
    "markeras.",
    "en": "You highlight in the document view by calling focus_anchor once per passage, with source_id "
    "from open_documents and quote set to that passage's exact words. Several calls on the same "
    "document highlight several passages. Never say you cannot mark or show the place. Confirm each "
    "passage only after its focus_anchor returns completed. Do not say a passage is highlighted unless "
    "you called focus_anchor for it. If the user says no highlight is visible, call focus_anchor "
    "immediately. When you have a comment on the passage, send it in comment in the same call. The "
    "comment appears on the highlight in your name. Omit comment when the passage should only be "
    "highlighted.",
}
_PARAGRAPHS["nb"] = _PARAGRAPHS["sv"]

_TOOL = "workspace.voice.tool.focus_anchor"
_TOOL_OLD = {
    "sv": "Markera verifierat dokumentankare. Bekräfta endast när rätt sida och markering visas.",
    "en": "Highlight a verified document anchor. Confirm only once the correct page and highlight are visible.",
    "nb": "Markera verifierat dokumentankare. Bekräfta endast när rätt sida och markering visas.",
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
