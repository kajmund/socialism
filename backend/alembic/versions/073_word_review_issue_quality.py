"""Separate short Word comments from explanations and materialization.

Revision ID: 073_word_review_issue_quality
Revises: 072_intent_interview_trust
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "073_word_review_issue_quality"
down_revision: Union[str, Sequence[str], None] = "072_intent_interview_trust"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "expertgranskning.word.comment_convergence"

_OLD_SV = (
    "Du konsoliderar expertkommentarer till Word-kommentarer. "
    "Deduplicera observationer/issues, inte experter. "
    "Komprimera konvergens. Bevara faktisk dissensus.\n\n"
    "Regler:\n"
    "- Samma kärnrisk eller samma observation från flera experter blir EN issue "
    "och EN Word-kommentar. Lista supporting_expert_ids för alla som stödjer den.\n"
    "- Samma expert ska inte ge två nästan identiska kommentarer på närliggande "
    "stycken för samma issue. Välj det mest specifika textankaret "
    "(konkret klausulrad, inte bara inledningsmeningen).\n"
    "- Syntetisera perspektiven i kommentar-fältet utan att upprepa dem. "
    "Juridisk, finansiell och operativ betydelse får rymmas i samma kommentar "
    "när kärnobservationen är densamma.\n"
    "- Dissensus får aldrig dedupliceras bort. Olika bedömningar eller "
    "rekommendationer ska bli separata issues (has_dissensus=true på var och en) "
    "eller en issue med has_dissensus=true där oenigheten är explicit. "
    "Hitta aldrig på falsk konsensus. Exempel: en expert tycker att "
    "dröjsmålsränta +15 procentenheter är acceptabelt och en annan vill sänka den "
    "- båda perspektiven måste överleva.\n"
    "- Varje inkommande observation_id ska ingå i exakt en issue.\n"
    "- paragraph_index måste vara ett ankare som redan finns på de "
    "grupperade observationerna. Hitta inte på ett annat stycke.\n"
    "- Om en granskningsavsikt finns i systemmeddelandet: följ den, inklusive "
    "partsställning. "
    "Granskande part är okänd om avsikten inte anger partsställning. "
    "Använd dokumentets partsbeteckningar. "
    "Skriv inte för er som kund eller du som kund. "
    "Vänd inte på dokumentfakta. Märk externa antaganden som antaganden.\n\n"
    "Avsnitt: {section_heading}\n\n"
    "Batch:\n{batch_text}\n\n"
    "Observationer:\n{observations}\n\n"
    "Returnera issues med observation_ids, paragraph_index, "
    "supporting_expert_ids, kommentar och has_dissensus."
)
_OLD_EN = (
    "You consolidate expert comments into Word comments. "
    "Deduplicate observations/issues, not experts. "
    "Compress convergence. Preserve actual dissensus.\n\n"
    "Rules:\n"
    "- The same core risk or observation from several experts becomes ONE issue "
    "and ONE Word comment. List supporting_expert_ids for everyone who supports it.\n"
    "- The same expert must not get two nearly identical comments on nearby "
    "paragraphs for the same issue. Choose the most specific text anchor "
    "(the concrete clause line, not just the introductory sentence).\n"
    "- Synthesize the perspectives in kommentar without repeating them. "
    "Legal, financial, and operational meaning may live in the same comment "
    "when the core observation is the same.\n"
    "- Dissensus must never be deduplicated away. Different assessments or "
    "recommendations must become separate issues (has_dissensus=true on each) "
    "or one issue with has_dissensus=true that states the disagreement explicitly. "
    "Never invent false consensus. Example: one expert finds default interest of "
    "+15 percentage points acceptable and another wants it lowered "
    "- both perspectives must survive.\n"
    "- Every incoming observation_id must appear in exactly one issue.\n"
    "- paragraph_index must be an anchor already present on the grouped "
    "observations. Do not invent another paragraph.\n"
    "- If a review intent is present in the system message: follow it, including "
    "party position. "
    "The reviewing party is unknown if the intent does not state a party. "
    "Use the document's party labels. "
    "Do not write for you as the customer or you as the client. "
    "Do not reverse document facts. Mark external assumptions as assumptions.\n\n"
    "Section: {section_heading}\n\n"
    "Batch:\n{batch_text}\n\n"
    "Observations:\n{observations}\n\n"
    "Return issues with observation_ids, paragraph_index, "
    "supporting_expert_ids, kommentar, and has_dissensus."
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
    op.add_column(
        "expertgranskning_results",
        sa.Column("explanation", sa.Text(), nullable=True),
    )
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
    op.drop_column("expertgranskning_results", "explanation")
