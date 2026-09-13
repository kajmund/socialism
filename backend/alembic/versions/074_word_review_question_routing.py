"""Cap Word moderator questions and add primary-anchor routing.

Revision ID: 074_word_review_question_routing
Revises: 073_word_review_issue_quality
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "074_word_review_question_routing"
down_revision: Union[str, Sequence[str], None] = "073_word_review_issue_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "expertgranskning.word.moderator.batch"

_OLD_SV = (
    "Du är moderator för en expertgranskning av ett Word-dokument. "
    "Förstå batchen i dokumentets helhet. Avgör om expertbedömning behövs "
    "och formulera i så fall konkreta granskningsfrågor. "
    "Gör inte specialistbedömningen och välj inte vilka experter som ska svara. "
    "Använd panelinformationen bara för att formulera relevanta frågor.\n\n"
    "Var konservativ. Skapa inte frågor bara för att text finns. "
    "Namn, telefon, e-post, kontaktuppgifter, ren metadata och trivial administration "
    "ska normalt inte granskas. Identifiera däremot sådant som kräver bedömning: "
    "oklarheter, motsägelser, risker, betydelsefulla antaganden, saknad information "
    "med faktisk betydelse, potentiella konsekvenser och genomförbarhetsproblem. "
    "Det är exempel, inte en domänspecifik checklista.\n\n"
    "Panel:\n{expert_list}\n\n"
    "Avsnitt: {section_heading}\n\n"
    "Den här batchen:\n{batch_text}\n\n"
    "Hela dokumentet ligger i systemmeddelandet. "
    "Om en granskningsavsikt finns där: formulera frågor utifrån den.\n\n"
    "Returnera needs_review, reason och questions. "
    "Varje fråga ska ha id, paragraph_indexes (bara index från batchen), "
    "question och why_it_matters. "
    "Om needs_review är false: tom questions-lista."
)
_OLD_EN = (
    "You moderate an expert review of a Word document. "
    "Understand the batch in the full document context. Decide whether expert "
    "assessment is needed and, if so, write concrete review questions. "
    "Do not make the specialist assessment and do not choose which experts should answer. "
    "Use the panel information only to formulate relevant questions.\n\n"
    "Be conservative. Do not create questions just because text exists. "
    "Names, phone numbers, email, contact details, pure metadata, and trivial "
    "administration should normally not be reviewed. Do identify things that need "
    "judgment: ambiguities, contradictions, risks, material assumptions, missing "
    "information that actually matters, potential consequences, and feasibility problems. "
    "These are examples, not a domain-specific checklist.\n\n"
    "Panel:\n{expert_list}\n\n"
    "Section: {section_heading}\n\n"
    "This batch:\n{batch_text}\n\n"
    "The full document is in the system message. "
    "If a review intent is present there: formulate questions from it.\n\n"
    "Return needs_review, reason, and questions. "
    "Each question must have id, paragraph_indexes (only indexes from the batch), "
    "question, and why_it_matters. "
    "If needs_review is false: empty questions list."
)


def _field(key: str) -> dict:
    return next(row for row in PROMPT_FIELDS if row["key"] == key)


def _update_defaults(conn, key: str, *, sv: str, en: str, nb: str) -> None:
    conn.execute(
        sa.text(
            "UPDATE prompt_fields "
            "SET default_sv = :sv, default_en = :en, default_nb = :nb "
            "WHERE key = :key"
        ).bindparams(sv=sv, en=en, nb=nb, key=key)
    )


def upgrade() -> None:
    field = _field(_KEY)
    defaults = field["defaults"]
    _update_defaults(
        op.get_bind(),
        _KEY,
        sv=defaults["sv"],
        en=defaults["en"],
        nb=defaults["nb"],
    )


def downgrade() -> None:
    _update_defaults(
        op.get_bind(),
        _KEY,
        sv=_OLD_SV,
        en=_OLD_EN,
        nb=_OLD_SV,
    )
