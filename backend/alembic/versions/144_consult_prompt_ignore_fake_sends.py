"""Do not let earlier fake consult replies count as a tool call.

Revision ID: 144_consult_prompt_ignore_fake_sends
Revises: 143_expert_tool_call_prompts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "144_consult_prompt_ignore_fake_sends"
down_revision: str | Sequence[str] | None = "143_expert_tool_call_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "chat.expert.consult_tool"
_PREVIOUS = {
    "sv": (
        "ask_expert är ett verktygsanrop, inte en mening i chatten. Det är det "
        "enda sättet en kollega får frågan. Anropa ask_expert innan du skriver "
        "till användaren. Sätt argumentet question till en fristående och tydlig "
        "formulering. Gör anropet när frågan ligger utanför din kompetens, när "
        "användaren ber dig fråga en kollega, och när användaren bekräftar en "
        "formulering du redan föreslagit. Skriv inte att frågan är skickad, att "
        "du skickar den eller att du återkommer. En sådan mening når ingen. "
        "Fråga inte om lov igen när användaren redan bett dig skicka. Anropa "
        "inte verktyget när du själv kan besvara frågan. När verktyget har "
        "svarat återger du kollegans svar. Skriv inte verktygets namn, JSON "
        "eller XML i den texten."
    ),
    "en": (
        "ask_expert is a tool call, not a sentence in the chat. It is the only "
        "way a colleague receives the question. Call ask_expert before you write "
        "to the user. Set the question argument to a clear, standalone "
        "formulation. Make the call when the question is outside your "
        "competence, when the user asks you to ask a colleague, and when the "
        "user confirms a formulation you already proposed. Do not write that the "
        "question has been sent, that you are sending it, or that you will come "
        "back. Such a sentence reaches no one. Do not ask permission again when "
        "the user has already asked you to send it. Do not call the tool when "
        "you can answer the question yourself. After the tool responds, relay "
        "the colleague's answer. Do not write the tool name, JSON, or XML in "
        "that text."
    ),
}


def _apply(conn, *, source: dict[str, str], target: dict[str, str]) -> None:
    for language, column in (
        ("sv", "default_sv"),
        ("en", "default_en"),
        ("nb", "default_nb"),
    ):
        old = source["sv"] if language == "nb" else source[language]
        new = target["sv"] if language == "nb" else target[language]
        conn.execute(
            sa.text(
                f"UPDATE prompt_fields SET {column} = :new "
                f"WHERE key = :key AND {column} = :old"
            ).bindparams(key=_KEY, old=old, new=new)
        )
        conn.execute(
            sa.text(
                "UPDATE prompt_overrides SET text = :new "
                "WHERE language = :language AND text = :old "
                "AND prompt_field_id = (SELECT id FROM prompt_fields WHERE key = :key)"
            ).bindparams(key=_KEY, language=language, old=old, new=new)
        )


def upgrade() -> None:
    target = next(row for row in PROMPT_FIELDS if row["key"] == _KEY)["defaults"]
    _apply(op.get_bind(), source=_PREVIOUS, target=target)


def downgrade() -> None:
    target = next(row for row in PROMPT_FIELDS if row["key"] == _KEY)["defaults"]
    _apply(op.get_bind(), source=target, target=_PREVIOUS)
