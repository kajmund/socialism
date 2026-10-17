"""A relation map on screen is readable by experts and expert groups."""

import sqlalchemy as sa
from alembic import op

revision = "171_shown_relations_are_readable"
down_revision = "170_shown_document_is_the_view"
branch_labels = None
depends_on = None

_REPLACEMENTS = (
    (
        "workspace.voice.system",
        (
            "När ett dokument visas i arbetsytan står texten under Dokument som visas, "
            "för alla experter. Läs den och svara utifrån den. Öppna inte dokumentet för "
            "att läsa det."
        ),
        (
            "När ett dokument visas i arbetsytan står texten under Dokument som visas, "
            "för alla experter. Läs den och svara utifrån den. Öppna inte dokumentet för "
            "att läsa det. När en relationskarta visas står noderna och kanterna under "
            "Relationskartan som visas, för alla experter. Läs den och svara utifrån den. "
            "Öppna inte kartan för att läsa den. Säg inte att den saknas."
        ),
        (
            "When a document is on screen, that text is already in the context for every "
            "expert. Read it and answer from it. Do not open the document in order to read it."
        ),
        (
            "When a document is on screen, that text is already in the context for every "
            "expert. Read it and answer from it. Do not open the document in order to read it. "
            "When a relation map is on screen, its nodes and edges are already in the context "
            "for every expert. Read them and answer from them. Do not open the map in order to "
            "read it. Do not say it is missing."
        ),
    ),
    (
        "workspace.chat.turn",
        (
            "När active_artifact_id är satt visas det dokumentet redan, och texten finns i "
            "kontexten. Läs den. Säg inte att det saknas i vyn eller bland filerna."
        ),
        (
            "När active_artifact_id är satt visas det dokumentet eller den relationskartan "
            "redan, och texten finns i kontexten. Läs den. Säg inte att det saknas i vyn "
            "eller bland filerna."
        ),
        (
            "When active_artifact_id is set, that document is already on screen and its text "
            "is in the context. Read it. Do not say it is missing from the view or from the files."
        ),
        (
            "When active_artifact_id is set, that document or relation map is already on screen "
            "and its text is in the context. Read it. Do not say it is missing from the view "
            "or from the files."
        ),
    ),
)


def _replace(key: str, language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) WHERE key = :key"
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
