"""An expert can leave a comment with the passage they mark."""

import sqlalchemy as sa
from alembic import op

revision = "175_passage_mark_comments"
down_revision = "174_passage_comments"
branch_labels = None
depends_on = None

_REPLACEMENTS = (
    (
        "workspace.voice.system",
        "Om användaren säger att ingen markering syns, anropa focus_anchor direkt.",
        "Om användaren säger att ingen markering syns, anropa focus_anchor direkt. När du har en kommentar till passagen skickar du den i comment i samma anrop. Kommentaren visas vid markeringen i ditt namn. Utelämna comment när passagen bara ska markeras.",
        "If the user says no highlight is visible, call focus_anchor immediately.",
        "If the user says no highlight is visible, call focus_anchor immediately. When you have a comment on the passage, send it in comment in the same call. The comment appears on the highlight in your name. Omit comment when the passage should only be highlighted.",
    ),
    (
        "workspace.voice.tool.focus_anchor",
        "Säg inte att en passage är markerad om det anropet inte har svarat completed. Söker inte efter innehåll och läser inte omgivande text.",
        "Säg inte att en passage är markerad om det anropet inte har svarat completed. Sätt comment till din kommentar om passagen i samma anrop när du har en. Den visas vid markeringen i ditt namn. Utelämna comment när passagen bara ska markeras. Söker inte efter innehåll och läser inte omgivande text.",
        "Do not say a passage is highlighted unless that call has returned completed. Does not search for content or read surrounding text.",
        "Do not say a passage is highlighted unless that call has returned completed. Set comment to your comment on the passage in the same call when you have one. It appears on the highlight in your name. Omit comment when the passage should only be highlighted. Does not search for content or read surrounding text.",
    ),
)


def _replace(key: str, language: str, old: str, new: str) -> None:
    column = f"default_{language}"
    connection = op.get_bind()
    connection.execute(
        sa.text(f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) WHERE key = :key"),
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
    with op.batch_alter_table("workspace_passage_comments") as batch:
        batch.add_column(
            sa.Column("author_kind", sa.String(16), nullable=False, server_default="user")
        )
        batch.add_column(sa.Column("expert_id", sa.String(64), nullable=True))
        batch.alter_column("author_user_id", existing_type=sa.String(64), nullable=True)
    _apply(True)


def downgrade() -> None:
    _apply(False)
    op.execute(sa.text("DELETE FROM workspace_passage_comments WHERE author_user_id IS NULL"))
    with op.batch_alter_table("workspace_passage_comments") as batch:
        batch.alter_column("author_user_id", existing_type=sa.String(64), nullable=False)
        batch.drop_column("expert_id")
        batch.drop_column("author_kind")
