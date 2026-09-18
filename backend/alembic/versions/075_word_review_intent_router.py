"""Intent-aware moderator context and fast Word expert router.

Revision ID: 075_word_review_intent_router
Revises: 074_word_review_question_routing
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "075_word_review_intent_router"
down_revision: Union[str, Sequence[str], None] = "074_word_review_question_routing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODERATOR_KEY = "expertgranskning.word.moderator.batch"
_ROUTER_KEY = "expertgranskning.word.expert.router"

_OLD_MODERATOR_SV = (
    "Du är moderator för en expertgranskning av ett Word-dokument. "
    "Förstå batchen i dokumentets helhet. Avgör om expertbedömning behövs "
    "och formulera i så fall högst två konkreta granskningsfrågor, "
    "ordnade efter materialitet och betydelse (viktigast först). "
    "Gör inte specialistbedömningen. "
    "Om du är säker på vilka experter som ska svara får du rekommendera "
    "högst två slot-id från panelen; annars lämna recommended_expert_ids tomt.\n\n"
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
    "Returnera needs_review, reason och questions. Högst två frågor. "
    "Varje fråga ska ha id, paragraph_indexes (bara index från batchen), "
    "primary_anchor_paragraph_index (ett av frågans paragraph_indexes), "
    "question, why_it_matters och valfritt recommended_expert_ids "
    "(högst två slot-id från panelen, bara när du är säker). "
    "Om needs_review är false: tom questions-lista."
)
_OLD_MODERATOR_EN = (
    "You moderate an expert review of a Word document. "
    "Understand the batch in the full document context. Decide whether expert "
    "assessment is needed and, if so, write at most two concrete review questions, "
    "ordered by materiality and importance (most important first). "
    "Do not make the specialist assessment. "
    "If you are confident which experts should answer, you may recommend at most "
    "two slot ids from the panel; otherwise leave recommended_expert_ids empty.\n\n"
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
    "Return needs_review, reason, and questions. At most two questions. "
    "Each question must have id, paragraph_indexes (only indexes from the batch), "
    "primary_anchor_paragraph_index (one of that question's paragraph_indexes), "
    "question, why_it_matters, and optional recommended_expert_ids "
    "(at most two panel slot ids, only when you are confident). "
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
    conn = op.get_bind()
    moderator = _field(_MODERATOR_KEY)
    defaults = moderator["defaults"]
    _update_defaults(
        conn,
        _MODERATOR_KEY,
        sv=defaults["sv"],
        en=defaults["en"],
        nb=defaults["nb"],
    )
    exists = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(
            key=_ROUTER_KEY
        )
    ).fetchone()
    if exists is not None:
        return
    field = _field(_ROUTER_KEY)
    labels = field["label"]
    hints = field["hint"]
    router_defaults = field["defaults"]
    conn.execute(
        sa.text(
            "INSERT INTO prompt_fields ("
            "key, modules, section, label_sv, label_en, hint_sv, hint_en, "
            "default_sv, default_en, default_nb, active"
            ") VALUES ("
            ":key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
            ":default_sv, :default_en, :default_nb, TRUE"
            ")"
        ).bindparams(
            sa.bindparam("modules", type_=sa.JSON()),
            key=_ROUTER_KEY,
            modules=modules_for_prompt_key(_ROUTER_KEY),
            section=field["section"],
            label_sv=labels["sv"],
            label_en=labels["en"],
            hint_sv=hints["sv"],
            hint_en=hints["en"],
            default_sv=router_defaults["sv"],
            default_en=router_defaults["en"],
            default_nb=router_defaults["nb"],
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    _update_defaults(
        conn,
        _MODERATOR_KEY,
        sv=_OLD_MODERATOR_SV,
        en=_OLD_MODERATOR_EN,
        nb=_OLD_MODERATOR_SV,
    )
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(
            key=_ROUTER_KEY
        )
    ).fetchone()
    if field_id is None:
        return
    conn.execute(
        sa.text(
            "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
        ).bindparams(field_id=field_id[0])
    )
    conn.execute(
        sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(
            key=_ROUTER_KEY
        )
    )
