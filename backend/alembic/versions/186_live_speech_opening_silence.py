"""Live Speech opening stays silent without history instead of greeting.

Revision ID: 186_live_speech_opening_silence
Revises: 185_marks_are_fetched_when_asked
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "186_live_speech_opening_silence"
down_revision: str | Sequence[str] | None = "185_marks_are_fetched_when_asked"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "chat.expert.live_speech_opening"

_NEW_SV = (
    "Du öppnar röstsamtalet. Svara med JSON {\"phrase\":\"...\",\"silence\":false} "
    "eller silence. Finns det historik: en eller två korta talade meningar som tar "
    "upp tråden från senaste chatten. Var konkret om det ni just pratade om. "
    "Hitta inte på nya fakta. Ingen sammanfattning, ingen verktygsplan och ingen "
    "fråga som vad kan jag hjälpa dig med. Om historiken saknas: svara med "
    "silence. Hälsa inte och ställ ingen fråga — användaren inleder."
)

_NEW_EN = (
    "You are opening the voice session. Reply with JSON "
    "{\"phrase\":\"...\",\"silence\":false} or silence. If there is history: one "
    "or two short spoken sentences that pick up the latest chat. Be concrete "
    "about what you just discussed. Do not invent facts. No summary, no tool "
    "plan, and no question like what can I help you with. If there is no "
    "history: reply with silence. Do not greet and do not ask a question — the "
    "user begins."
)

_OLD_SV = (
    "Du öppnar röstsamtalet. Svara med JSON {\"phrase\":\"...\",\"silence\":false} "
    "eller silence. En eller två korta talade meningar som tar upp tråden från "
    "senaste chatten. Var konkret om det ni just pratade om. Hitta inte på nya "
    "fakta. Ingen sammanfattning, ingen verktygsplan och inte hur kan jag hjälpa. "
    "Om historiken saknas, hälsa kort som experten."
)

_OLD_EN = (
    "You are opening the voice session. Reply with JSON "
    "{\"phrase\":\"...\",\"silence\":false} or silence. One or two short spoken "
    "sentences that pick up the latest chat. Be concrete about what you just "
    "discussed. Do not invent facts. No summary, no tool plan, and no how can I "
    "help. If there is no history, greet briefly as the expert."
)


def _set_defaults(sv: str, en: str) -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT id FROM prompt_fields WHERE key = :key"
        ),
        {"key": _KEY},
    ).fetchone()
    if row is None:
        return
    conn.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :sv "
            "WHERE id = :id"
        ),
        {"id": row[0], "sv": sv, "en": en},
    )


def upgrade() -> None:
    _set_defaults(_NEW_SV, _NEW_EN)


def downgrade() -> None:
    _set_defaults(_OLD_SV, _OLD_EN)
