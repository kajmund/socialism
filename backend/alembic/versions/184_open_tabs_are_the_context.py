"""Open tabs are identified in the turn. Document text is not copied in."""

import sqlalchemy as sa
from alembic import op

revision = "184_open_tabs_are_the_context"
down_revision = "183_reasoning_assessment_questions"
branch_labels = None
depends_on = None

_REPLACEMENTS = (
    (
        "workspace.chat.turn",
        "Text för det som visas finns separat i turens kontext och ska läsas direkt.",
        "Bara öppna flikar står i kontexten, med source_id eller artifact_id. "
        "Dokumenttext ingår inte. Läs den med read_source.",
        "Text for what is shown is supplied separately in the turn context and should be read directly.",
        "Only open tabs are in the context, with source_id or artifact_id. "
        "Document text is not included. Read it with read_source.",
    ),
    (
        "workspace.voice.task.document_locate",
        "Text som redan visas läser du direkt ur turens kontext.",
        "Dokumenttext ingår inte i turens kontext.",
        "Read text already on screen directly from the turn context.",
        "Document text is not included in the turn context.",
    ),
    (
        "workspace.voice.tool.get_workspace_context",
        "Ett dokument som visas har texten i kontexten för alla experter. "
        "Öppna det inte för att läsa det. Ett dokument som inte visas läses med "
        "read_source via samma source_id.",
        "Kontexten listar bara öppna flikar med id. Dokumenttext ingår inte. "
        "Läs den med read_source.",
        "A document on screen already has its text in the context for every expert. "
        "Do not open it in order to read it. A document that is not on screen is read "
        "with read_source through the same source_id.",
        "The context lists only open tabs, with their ids. Document text is not included. "
        "Read it with read_source.",
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
