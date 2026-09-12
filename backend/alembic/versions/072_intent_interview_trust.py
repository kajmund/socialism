"""Treat Word snapshot as user data in the intent-interview prompt.

Revision ID: 072_intent_interview_trust
Revises: 071_intent_interview
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "072_intent_interview_trust"
down_revision: Union[str, Sequence[str], None] = "071_intent_interview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "expertgranskning.word.intent_interview"

_OLD_HINT_SV = "Dokumentet ligger i systemmeddelandet. Inga platshållare."
_OLD_HINT_EN = "The document is in the system message. No placeholders."
_OLD_SV = (
    "Du skapar en kort avsiktsintervju före expertgranskning av ett Word-dokument. "
    "Dokumentet ligger i systemmeddelandet.\n\n"
    "Regler:\n"
    "- Högst 5 frågor. Färre är bättre. Noll frågor om dokumentet redan ger "
    "tillräcklig kontext för en meningsfull granskning.\n"
    "- Varje fråga måste kunna ändra den efterföljande expertanalysen på ett "
    "substantiellt sätt.\n"
    "- Fråga inte efter information som dokumentet redan tydligt fastställer.\n"
    "- Föredra single_choice eller multi_choice. Använd free_text bara när "
    "klickbara alternativ inte räcker.\n"
    "- Alternativ ska vara ömsesidigt begripliga och korta.\n"
    "- Frågorna ska vara specifika för just detta dokument och dess faktiska "
    "osäkerheter.\n"
    "- Anta inte att dokumentet är juridiskt, ett avtal eller någon annan "
    "specifik genre. document_type är bara en kort beskrivande etikett, "
    "inte en växel till en mall.\n"
    "- question id och option value: korta maskinläsbara slug-strängar "
    "(a-z, 0-9, underscore), unika inom intervjun.\n"
    "- required=true bara när svaret behövs för en meningsfull granskning.\n"
    "- rationale förklarar varför svaret ändrar analysen.\n\n"
    "Returnera document_type och questions."
)
_OLD_EN = (
    "You create a short intent interview before an expert review of a Word "
    "document. The document is in the system message.\n\n"
    "Rules:\n"
    "- At most 5 questions. Fewer is better. Zero questions if the document "
    "already gives enough context for a meaningful review.\n"
    "- Every question must be able to change the downstream expert analysis "
    "in a material way.\n"
    "- Do not ask for information the document already clearly establishes.\n"
    "- Prefer single_choice or multi_choice. Use free_text only when clickable "
    "options are not enough.\n"
    "- Options must be mutually understandable and concise.\n"
    "- Questions must be specific to this document and its actual uncertainties.\n"
    "- Do not assume the document is legal, a contract, or any other specific "
    "genre. document_type is only a short descriptive label, not a switch "
    "into a template.\n"
    "- question id and option value: short machine-readable slugs "
    "(a-z, 0-9, underscore), unique within the interview.\n"
    "- required=true only when the answer is needed for a meaningful review.\n"
    "- rationale explains why the answer changes the analysis.\n\n"
    "Return document_type and questions."
)


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def _update_field(
    conn,
    key: str,
    *,
    sv: str,
    en: str,
    nb: str,
    hint_sv: str,
    hint_en: str,
) -> None:
    conn.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb, "
            "hint_sv = :hint_sv, hint_en = :hint_en "
            "WHERE key = :key"
        ).bindparams(
            sv=sv,
            en=en,
            nb=nb,
            hint_sv=hint_sv,
            hint_en=hint_en,
            key=key,
        )
    )


def upgrade() -> None:
    field = _field(_KEY)
    defaults = field["defaults"]
    hints = field["hint"]
    _update_field(
        op.get_bind(),
        _KEY,
        sv=defaults["sv"],
        en=defaults["en"],
        nb=defaults["nb"],
        hint_sv=hints["sv"],
        hint_en=hints["en"],
    )


def downgrade() -> None:
    _update_field(
        op.get_bind(),
        _KEY,
        sv=_OLD_SV,
        en=_OLD_EN,
        nb=_OLD_SV,
        hint_sv=_OLD_HINT_SV,
        hint_en=_OLD_HINT_EN,
    )
