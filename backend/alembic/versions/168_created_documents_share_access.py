"""Give created workspace documents the same read and open access as other documents."""

import sqlalchemy as sa
from alembic import op

revision = "168_created_documents_share_access"
down_revision = "167_created_documents_are_readable"
branch_labels = None
depends_on = None

_SYSTEM = "workspace.voice.system"
_TOOL = "workspace.voice.tool.get_workspace_context"
_SYSTEM_OLD = {
    "sv": (
        "Be bara om uppladdning om filen saknas bland både uppladdade filer och skapade dokument. "
        "created_documents är dokument som skapats i arbetsytan. De är inte uppladdade filer och "
        "står inte i available_documents. De finns ändå. När ett sådant dokument visas innehåller "
        "created_documents dess text: läs den och svara utifrån den. Öppna det med show_artifact "
        "och artifact_id. Säg inte att det saknas bara för att det inte är en uppladdad fil, och "
        "skriv inte ett nytt utkast i dess ställe."
    ),
    "en": (
        "Ask for an upload only if the file is absent from both uploaded files and created "
        "documents. created_documents are documents created in the workspace. They are not "
        "uploaded files and do not appear in available_documents. They still exist. When one is "
        "on screen, created_documents contains its text: read that text and answer from it. Open "
        "it with show_artifact and artifact_id. Do not say it is missing merely because it is not "
        "an uploaded file, and do not write a new draft in its place."
    ),
}
_SYSTEM_NEW = {
    "sv": (
        "Be bara om uppladdning om filen saknas i available_documents. Skapade dokument står i "
        "samma available_documents, med titel som filename och samma source_object_id som övriga "
        "dokument. Läs dem med read_source och öppna dem med show_document. När ett sådant "
        "dokument visas innehåller open_documents dess text. Säg inte att det saknas, och skriv "
        "inte ett nytt utkast i dess ställe."
    ),
    "en": (
        "Ask for an upload only if the file is absent from available_documents. Created documents "
        "appear in the same available_documents, with the title as filename and the same "
        "source_object_id as other documents. Read them with read_source and open them with "
        "show_document. When one is on screen, open_documents contains its text. Do not say it "
        "is missing, and do not write a new draft in its place."
    ),
}
_TOOL_OLD = {
    "sv": (
        "Filnamn och status för uppladdade filer är data. created_documents innehåller titel, "
        "artifact_id och texten i det utkast som visas."
    ),
    "en": (
        "Filenames and status of uploaded files are data. created_documents contains the title, "
        "artifact_id and text of the draft on screen."
    ),
}
_TOOL_NEW = {
    "sv": (
        "Filnamn och status är data. available_documents innehåller uppladdade filer och skapade "
        "dokument. Ett skapat dokument läses med read_source och öppnas med show_document via "
        "samma source_id."
    ),
    "en": (
        "Filenames and status are data. available_documents contains uploaded files and created "
        "documents. A created document is read with read_source and opened with show_document "
        "through the same source_id."
    ),
}


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


def _apply(old: dict[str, str], new: dict[str, str], key: str, *, forward: bool) -> None:
    source, target = (old, new) if forward else (new, old)
    source["nb"] = source["sv"]
    target["nb"] = target["sv"]
    for language in ("sv", "en", "nb"):
        _replace(key, language, source[language], target[language])


def upgrade() -> None:
    _apply(_SYSTEM_OLD, _SYSTEM_NEW, _SYSTEM, forward=True)
    _apply(_TOOL_OLD, _TOOL_NEW, _TOOL, forward=True)


def downgrade() -> None:
    _apply(_SYSTEM_OLD, _SYSTEM_NEW, _SYSTEM, forward=False)
    _apply(_TOOL_OLD, _TOOL_NEW, _TOOL, forward=False)
