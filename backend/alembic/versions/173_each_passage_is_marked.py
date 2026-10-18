"""Each passage an expert marks is delivered, not only the first one."""

import sqlalchemy as sa
from alembic import op

revision = "173_each_passage_is_marked"
down_revision = "172_passage_marks_name_the_author"
branch_labels = None
depends_on = None

_REPLACEMENTS = (
    (
        "workspace.voice.system",
        "Du markerar i dokumentvyn genom att anropa focus_anchor med source_id från open_documents och quote med de exakta orden, till exempel kundens namn. Säg aldrig att du inte kan markera eller visa platsen. Bekräfta markeringen först när focus_anchor har svarat completed. Om användaren säger att ingen markering syns, anropa focus_anchor direkt.",
        "Du markerar i dokumentvyn genom att anropa focus_anchor en gång per passage, med source_id från open_documents och quote med just den passagens exakta ord. Flera anrop på samma dokument markerar flera passager. Säg aldrig att du inte kan markera eller visa platsen. Bekräfta varje passage först när dess focus_anchor har svarat completed. Säg inte att en passage är markerad om du inte anropat focus_anchor för den. Om användaren säger att ingen markering syns, anropa focus_anchor direkt.",
        "You highlight in the document view by calling focus_anchor with source_id from open_documents and quote set to the exact words, such as the customer name. Never say you cannot mark or show the place. Confirm the highlight only after focus_anchor returns completed. If the user says no highlight is visible, call focus_anchor immediately.",
        "You highlight in the document view by calling focus_anchor once per passage, with source_id from open_documents and quote set to that passage's exact words. Several calls on the same document highlight several passages. Never say you cannot mark or show the place. Confirm each passage only after its focus_anchor returns completed. Do not say a passage is highlighted unless you called focus_anchor for it. If the user says no highlight is visible, call focus_anchor immediately.",
    ),
    (
        "workspace.voice.tool.focus_anchor",
        "Markera en redan identifierad passage i dokumentvyn och flytta vyn dit. Skicka source_id och quote med de exakta orden. Söker inte efter innehåll och läser inte omgivande text. Bekräfta först när markeringen syns.",
        "Markera en redan identifierad passage. Anropa en gång per passage, med source_id och quote satt till just den passagens exakta ord. Flera anrop på samma dokument markerar flera passager. Säg inte att en passage är markerad om det anropet inte har svarat completed. Söker inte efter innehåll och läser inte omgivande text.",
        "Highlight an already identified passage in the document view and move the view there. Send source_id and quote with the exact words. Does not search for content or read surrounding text. Confirm only once the highlight is visible.",
        "Highlight an already identified passage. Call it once per passage, with source_id and quote set to that passage's exact words. Several calls on the same document highlight several passages. Do not say a passage is highlighted unless that call has returned completed. Does not search for content or read surrounding text.",
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
