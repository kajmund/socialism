"""The active created document is the view, even when source tabs are open."""

import sqlalchemy as sa
from alembic import op

revision = "170_shown_document_is_the_view"
down_revision = "169_shown_documents_are_readable"
branch_labels = None
depends_on = None

_KEY = "workspace.chat.turn"
_REPLACEMENTS = (
    (
        "En tom documents-lista betyder att vyn är tom; öppna dokumentet ändå.",
        "documents är källflikar. När active_artifact_id är satt är det skapade dokumentet "
        "det som visas, inte documents. En tom documents-lista utan active_artifact_id "
        "betyder att vyn är tom; öppna dokumentet ändå.",
        "An empty documents list means the view is empty; open the document anyway.",
        "documents are source tabs. When active_artifact_id is set, that created document "
        "is what is on screen, not documents. An empty documents list without "
        "active_artifact_id means the view is empty; open the document anyway.",
    ),
    (
        "Säg att något visas eller markerats först efter att verktyget har körts.",
        "Säg att du just har öppnat eller markerat något först efter att verktyget har kört. "
        "När active_artifact_id är satt visas det dokumentet redan, och texten finns i "
        "kontexten. Läs den. Säg inte att det saknas i vyn eller bland filerna.",
        "Say that something is shown or highlighted only after the tool has run.",
        "Say that you just opened or highlighted something only after the tool has run. "
        "When active_artifact_id is set, that document is already on screen and its text "
        "is in the context. Read it. Do not say it is missing from the view or from the files.",
    ),
)


def _replace(language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) WHERE key = :key"
        ),
        {"key": _KEY, "old": old, "new": new},
    )
    connection.execute(
        sa.text(
            "UPDATE prompt_overrides SET text = replace(text, :old, :new) "
            "WHERE language = :language AND prompt_field_id = "
            "(SELECT id FROM prompt_fields WHERE key = :key)"
        ),
        {"key": _KEY, "language": language, "old": old, "new": new},
    )


def _apply(forward: bool) -> None:
    rows = _REPLACEMENTS if forward else reversed(_REPLACEMENTS)
    for old_sv, new_sv, old_en, new_en in rows:
        source = {"sv": old_sv, "en": old_en, "nb": old_sv}
        target = {"sv": new_sv, "en": new_en, "nb": new_sv}
        if not forward:
            source, target = target, source
        for language in ("sv", "en", "nb"):
            _replace(language, source[language], target[language])


def upgrade() -> None:
    _apply(True)


def downgrade() -> None:
    _apply(False)
