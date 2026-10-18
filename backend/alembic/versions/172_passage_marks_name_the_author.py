"""Experts can see who marked which passage."""

import sqlalchemy as sa
from alembic import op

revision = "172_passage_marks_name_the_author"
down_revision = "171_shown_relations_are_readable"
branch_labels = None
depends_on = None

_REPLACEMENTS = (
    (
        "workspace.voice.system",
        "Arbetsytans kontext innehåller valt kunskapsområde, synliga dokument, markering och aktiv dokumentrevision.",
        "Arbetsytans kontext innehåller valt kunskapsområde, synliga dokument, markering, vem som markerat passagen och aktiv dokumentrevision.",
        "Workspace context contains selected knowledge scope, visible documents, selection and active document revision.",
        "Workspace context contains selected knowledge scope, visible documents, selection, who marked the passage and active document revision.",
    ),
    (
        "workspace.chat.turn",
        "exact_text är texten användaren har markerat.",
        "exact_text är texten användaren har markerat. Markeringar i dokumenten anger vem som markerat vilken passage.",
        "exact_text is the text the user selected.",
        "exact_text is the text the user selected. The marks section names who marked which passage.",
    ),
    (
        "workspace.voice.tool.get_workspace_context",
        "Flyttar inte vyn och söker inte.",
        "passage_marks anger vem som markerat vilken passage. Flyttar inte vyn och söker inte.",
        "Does not move the view or search.",
        "passage_marks names who marked which passage. Does not move the view or search.",
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
