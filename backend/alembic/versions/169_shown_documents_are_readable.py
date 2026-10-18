"""A document already on screen is readable without opening it again."""

import sqlalchemy as sa
from alembic import op

revision = "169_shown_documents_are_readable"
down_revision = "168_created_documents_share_access"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_TOOL = "workspace.voice.tool.get_workspace_context"
_REPLACEMENTS = (
    (
        _SYSTEM,
        (
            "Läs dem med read_source och öppna dem med show_document. När ett sådant "
            "dokument visas innehåller open_documents dess text."
        ),
        (
            "När ett dokument visas i arbetsytan står texten under Dokument som visas, "
            "för alla experter. Läs den och svara utifrån den. Öppna inte dokumentet för "
            "att läsa det."
        ),
        (
            "Read them with read_source and open them with show_document. When one is "
            "on screen, open_documents contains its text."
        ),
        (
            "When a document is on screen, that text is already in the context for every "
            "expert. Read it and answer from it. Do not open the document in order to read it."
        ),
    ),
    (
        _SYSTEM,
        "open_documents i kontexten är text från dokument som visas, eller från det enda färdiga dokumentet.",
        "Dokument som visas i kontexten är texten för de dokument som ligger framme, för alla experter.",
        "open_documents in the context is text from documents on screen, or from the only ready document.",
        "The documents on screen in the context are the text of what is already open, for every expert.",
    ),
    (
        _SYSTEM,
        "Om svaret saknas i open_documents, anropa read_source",
        "Om svaret saknas i Dokument som visas, anropa read_source",
        "If the answer is not in open_documents, call read_source",
        "If the answer is not in the documents on screen, call read_source",
    ),
    (
        _TOOL,
        "Ett skapat dokument läses med read_source och öppnas med show_document via samma source_id.",
        (
            "Ett dokument som visas har texten i kontexten för alla experter. Öppna det inte "
            "för att läsa det. Ett dokument som inte visas läses med read_source via samma source_id."
        ),
        "A created document is read with read_source and opened with show_document through the same source_id.",
        (
            "A document on screen already has its text in the context for every expert. Do not "
            "open it in order to read it. A document that is not on screen is read with read_source "
            "through the same source_id."
        ),
    ),
)


def _replace(key: str, language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) "
            "WHERE key = :key"
        ),
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


def _apply(forward: bool) -> None:
    rows = _REPLACEMENTS if forward else reversed(_REPLACEMENTS)
    for key, old_sv, new_sv, old_en, new_en in rows:
        source = {"sv": old_sv, "en": old_en, "nb": old_sv}
        target = {"sv": new_sv, "en": new_en, "nb": new_sv}
        if not forward:
            source, target = target, source
        for language in ("sv", "en", "nb"):
            _replace(key, language, source[language], target[language])


def upgrade() -> None:
    _apply(True)


def downgrade() -> None:
    _apply(False)
