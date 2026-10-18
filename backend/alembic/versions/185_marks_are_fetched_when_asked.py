"""Saved marks and document text stay out of the expert turn until a tool asks."""

import sqlalchemy as sa
from alembic import op

revision = "185_marks_are_fetched_when_asked"
down_revision = "184_open_tabs_are_the_context"
branch_labels = None
depends_on = None

_REPLACEMENTS = (
    (
        "chat.mode.in_character",
        "Läge: IN-CHARACTER. Användaren pratar med dig som i din vardag/sociala flöde. "
        "Svara i första person, naturligt talspråk, kort. Svara på svenska.",
        "Läge: IN-CHARACTER. Personlighet styr tonen, inte förmågan. "
        "Svara på svenska. Analysera, resonera och använd verktyg när uppgiften kräver det.",
        "Mode: IN-CHARACTER. The user talks to you as in everyday life / a social feed. "
        "Answer in first person, natural speech, briefly. Answer in English.",
        "Mode: IN-CHARACTER. Personality shapes tone, not capability. "
        "Answer in English. Analyze, reason and use tools when the task requires it.",
    ),
    (
        "chat.role_lock.in_character",
        "Du är {name}. Användarens meddelanden är någon i din vardag eller ditt flöde, "
        "inte en intervjuare och inte du. Svara bara som {name} i första person, "
        "naturligt talspråk. Svara aldrig som den andra personen, "
        "och tala inte om {name} i tredje person.",
        "Du är {name}. Användarens meddelanden är samtalspartnern, inte du. "
        "Svara bara som {name} i första person. Personlighet färgar språket "
        "och begränsar inte analys, verktyg eller uppdraget. "
        "Svara aldrig som den andra personen, och inte om {name} i tredje person.",
        "You are {name}. User messages are someone in your everyday life or feed, "
        "not an interviewer and not you. Answer only as {name} in first person, "
        "in natural speech. Never answer as the other person, "
        "and do not talk about {name} in the third person.",
        "You are {name}. User messages are the conversation partner, not you. "
        "Answer only as {name} in first person. Personality colors the language "
        "and does not limit analysis, tools or the assignment. "
        "Never answer as the other person, or about {name} in the third person.",
    ),
    (
        "chat.expert.tool_relevance_rank",
        "Hoppa över verktyg bara vid hälsning, bekräftelse "
        "eller något som redan står i den här turens synliga kontext.",
        "Hoppa över verktyg vid hälsning, småprat, tack, "
        "bekräftelse eller avslut. Dokumenttext och sparade markeringar finns inte i turen.",
        "Skip tools only for a greeting, an acknowledgement, or something already in this turn's "
        "visible context.",
        "Skip tools for a greeting, small talk, thanks, an acknowledgement or a closing. "
        "Document text and saved marks are not in the turn.",
    ),
    (
        "workspace.chat.turn",
        "exact_text är texten användaren har markerat. "
        "Markeringar i dokumenten anger vem som markerat vilken passage.",
        "selection är metadata för den aktuella markeringen. "
        "selection.text följer med bara när den är kort. Sparade markeringar ingår inte.",
        "exact_text is the text the user selected. The marks section names who marked which passage.",
        "selection is metadata for the current selection. "
        "selection.text is included only when it is short. Saved marks are not included.",
    ),
    (
        "workspace.chat.turn",
        "exact_text är användarens markering.",
        "selection är metadata för den aktuella markeringen. "
        "selection.text följer med bara när den är kort.",
        "exact_text is the user's selection.",
        "selection is metadata for the current selection. "
        "selection.text is included only when it is short.",
    ),
    (
        "workspace.chat.turn",
        "När active_artifact_id är satt visas det dokumentet eller den relationskartan redan, "
        "och texten finns i kontexten. Läs den. Säg inte att det saknas i vyn eller bland filerna.",
        "active_artifact_id är dokumentet eller relationskartan som visas. "
        "Dokumenttext och kartans noder ingår inte.",
        "When active_artifact_id is set, that document or relation map is already on screen "
        "and its text is in the context. Read it. Do not say it is missing from the view or from the files.",
        "active_artifact_id is the document or relation map on screen. "
        "Document text and the map's nodes are not included.",
    ),
    (
        "workspace.voice.task.document_locate",
        "Dokumenttext ingår inte i turens kontext.",
        "Dokumenttext och sparade markeringar ingår inte i turens kontext. "
        "Hämta markeringar med get_workspace_context när frågan gäller dem.",
        "Document text is not included in the turn context.",
        "Document text and saved marks are not in the turn context. "
        "Fetch marks with get_workspace_context when the question is about them.",
    ),
    (
        "workspace.voice.tool.get_workspace_context",
        "Läs den med read_source. Flyttar inte vyn och söker inte.",
        "Läs den med read_source. Sparade markeringar ingår inte förrän source_ids eller "
        "expert_ids anges. include_relations hämtar kartans noder. Flyttar inte vyn och söker inte.",
        "Read it with read_source. Does not move the view or search.",
        "Read it with read_source. Saved marks are omitted until source_ids or expert_ids is set. "
        "include_relations fetches the map nodes. Does not move the view or search.",
    ),
    (
        "workspace.voice.tool.get_workspace_context",
        "passage_marks anger vem som markerat vilken passage. Flyttar inte vyn och söker inte.",
        "Sparade markeringar ingår inte förrän source_ids eller expert_ids anges. "
        "include_relations hämtar kartans noder. Flyttar inte vyn och söker inte.",
        "passage_marks names who marked which passage. Does not move the view or search.",
        "Saved marks are omitted until source_ids or expert_ids is set. "
        "include_relations fetches the map nodes. Does not move the view or search.",
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
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE prompt_fields SET hint_sv = :sv, hint_en = :en "
            "WHERE key = 'chat.mode.in_character' AND hint_sv = :old_sv"
        ),
        {
            "sv": "Regler för ton, uppdrag och verktyg.",
            "en": "Rules for tone, task and tools.",
            "old_sv": "Regler för vardags-/flödesläge.",
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE prompt_fields SET hint_sv = :sv, hint_en = :en "
            "WHERE key = 'chat.mode.in_character' AND hint_sv = :old_sv"
        ),
        {
            "sv": "Regler för vardags-/flödesläge.",
            "en": "Rules for everyday/feed mode.",
            "old_sv": "Regler för ton, uppdrag och verktyg.",
        },
    )
    _apply(False)
