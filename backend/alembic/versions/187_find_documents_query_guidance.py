"""Teach find_documents to write a compact query instead of the user's words.

Revision ID: 187_find_documents_query_guidance
Revises: 186_live_speech_opening_silence
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "187_find_documents_query_guidance"
down_revision: str | Sequence[str] | None = "186_live_speech_opening_silence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, language, old_substring, new_substring)
_CHAT_TURN_REPLACEMENTS = (
    (
        "workspace.chat.turn",
        "sv",
        "anropa find_documents med användarens egna ord",
        'anropa find_documents med query satt till en kompakt sökterm för dokumenttypen '
        'eller ämnet (till exempel "anställningsavtal") — inte en hel mening, inte '
        "användarens ordagranna formulering och utan negationer eller utfyllnadsord",
    ),
    (
        "workspace.chat.turn",
        "en",
        "call find_documents with the user's own words",
        'call find_documents with query set to a compact search term for the document '
        'type or subject (for example "employment agreements") — not a full sentence, '
        "not the user's verbatim wording, and without negations or filler words",
    ),
)

# (key, language, guard, sentence) — sentence appended once at the end.
_APPENDED_SENTENCES = (
    (
        "workspace.voice.tool.find_documents",
        "sv",
        "kompakt sökterm för dokumenttypen eller ämnet",
        ' Sätt query till en kompakt sökterm för dokumenttypen eller ämnet '
        '(till exempel "anställningsavtal") — inte en hel mening, inte användarens '
        "ordagranna formulering och utan negationer eller utfyllnadsord.",
    ),
    (
        "workspace.voice.tool.find_documents",
        "en",
        "compact search term for the document type or subject",
        ' Set query to a compact search term for the document type or subject '
        '(for example "employment agreements") — not a full sentence, not the '
        "user's verbatim wording, and without negations or filler words.",
    ),
    (
        "workspace.voice.task.document_find",
        "sv",
        "kompakt sökterm för dokumenttypen",
        ' Skriv query som en kompakt sökterm för dokumenttypen (till exempel '
        '"anställningsavtal") — inte en hel mening och inte användarens ordagranna '
        "formulering.",
    ),
    (
        "workspace.voice.task.document_find",
        "en",
        "compact search term for the document type",
        ' Write query as a compact search term for the document type (for example '
        '"employment agreements") — not a full sentence and not the user\'s '
        "verbatim wording.",
    ),
)


def _column_for(language: str) -> str:
    return f"default_{language}"


def _replace_substring(key: str, language: str, old: str, new: str) -> None:
    column = _column_for(language)
    op.get_bind().execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = replace({column}, :old, :new) "
            "WHERE key = :key"
        ),
        {"key": key, "old": old, "new": new},
    )


def _append_sentence(key: str, language: str, guard: str, sentence: str) -> None:
    column = _column_for(language)
    row = op.get_bind().execute(
        sa.text(f"SELECT id, {column} FROM prompt_fields WHERE key = :key"),
        {"key": key},
    ).fetchone()
    if row is None or guard in (row[1] or ""):
        return
    op.get_bind().execute(
        sa.text(f"UPDATE prompt_fields SET {column} = :text WHERE id = :id"),
        {"id": row[0], "text": f"{row[1] or ''}{sentence}"},
    )


def upgrade() -> None:
    for key, language, old, new in _CHAT_TURN_REPLACEMENTS:
        for lang in ("sv", "nb") if language == "sv" else ("en",):
            _replace_substring(key, lang, old, new)
    for key, language, guard, sentence in _APPENDED_SENTENCES:
        _append_sentence(key, language, guard, sentence)
        if language == "sv":
            _append_sentence(key, "nb", guard, sentence)


def downgrade() -> None:
    for key, language, old, new in reversed(_CHAT_TURN_REPLACEMENTS):
        for lang in ("sv", "nb") if language == "sv" else ("en",):
            _replace_substring(key, lang, new, old)
    for key, language, guard, sentence in _APPENDED_SENTENCES:
        _replace_substring(key, language, sentence, "")
        if language == "sv":
            _replace_substring(key, "nb", sentence, "")
