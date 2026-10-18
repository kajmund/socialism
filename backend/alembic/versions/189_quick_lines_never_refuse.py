"""Quick chat lines never refuse or decide what the expert can show.

The acknowledgment and progress lines are written by the fast model while the
full reply runs. They must only say that the expert is on it — never that the
expert cannot help, cannot answer, or cannot show a document. Whether a
document can be shown is decided by the full turn, not by the quick line.

Revision ID: 189_quick_lines_never_refuse
Revises: 188_workspace_context_structure
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "189_quick_lines_never_refuse"
down_revision: str | Sequence[str] | None = "188_workspace_context_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, language, guard, sentence) — sentence appended once at the end.
_APPENDED_SENTENCES = (
    (
        "chat.expert.quick_draft",
        "sv",
        "det avgör inte den här raden",
        " Säg aldrig att du inte kan hjälpa, svara eller visa ett dokument — det "
        "avgör inte den här raden.",
    ),
    (
        "chat.expert.quick_draft",
        "en",
        "this line does not decide that",
        " Never say you cannot help, answer, or show a document — this line does "
        "not decide that.",
    ),
    (
        "chat.expert.quick_progress",
        "sv",
        "det avgör inte den här raden",
        " Säg aldrig att du inte kan hjälpa, svara eller visa ett dokument — det "
        "avgör inte den här raden.",
    ),
    (
        "chat.expert.quick_progress",
        "en",
        "this line does not decide that",
        " Never say you cannot help, answer, or show a document — this line does "
        "not decide that.",
    ),
)


def _column_for(language: str) -> str:
    return f"default_{language}"


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


def _remove_sentence(key: str, language: str, sentence: str) -> None:
    column = _column_for(language)
    op.get_bind().execute(
        sa.text(
            f"UPDATE prompt_fields SET {column} = replace({column}, :old, '') "
            "WHERE key = :key"
        ),
        {"key": key, "old": sentence},
    )


def upgrade() -> None:
    for key, language, guard, sentence in _APPENDED_SENTENCES:
        _append_sentence(key, language, guard, sentence)
        if language == "sv":
            _append_sentence(key, "nb", guard, sentence)


def downgrade() -> None:
    for key, language, _guard, sentence in reversed(_APPENDED_SENTENCES):
        _remove_sentence(key, language, sentence)
        if language == "sv":
            _remove_sentence(key, "nb", sentence)
