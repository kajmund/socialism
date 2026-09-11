"""Word comment anchors, party-neutral prompts, and JSON retry.

Revision ID: 065_word_comment_anchor_retry
Revises: 064_word_comment_convergence
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "065_word_comment_anchor_retry"
down_revision: Union[str, Sequence[str], None] = "064_word_comment_convergence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_COMMENT_SV = (
    "Din roll: {label}\n"
    "Profil: {profile}\n\n"
    "Hela dokumentet ligger i systemmeddelandet.\n\n"
    "Avsnitt: {section_heading}\n"
    "Klausulnummer (internt): {list_string}\n\n"
    "Granskningsfråga: {question}\n"
    "Varför det spelar roll: {why_it_matters}\n\n"
    "Relevant dokumenttext:\n{paragraph_text}\n\n"
    "Ge en konkret expertbedömning. Återberätta inte texten och kommentera inte "
    "enbart att information finns. Förklara vad som är relevant, problematiskt, "
    "osäkert eller bör förbättras. Tom kommentar betyder att du hoppar över. "
    "Inga tekniska termer. Prefixera inte med klausulnummer."
)
_OLD_COMMENT_EN = (
    "Your role: {label}\n"
    "Profile: {profile}\n\n"
    "The full document is in the system message.\n\n"
    "Section: {section_heading}\n"
    "Clause number (internal): {list_string}\n\n"
    "Review question: {question}\n"
    "Why it matters: {why_it_matters}\n\n"
    "Relevant document text:\n{paragraph_text}\n\n"
    "Give a concrete expert assessment. Do not retell the text and do not only "
    "note that the information exists. Explain what is relevant, problematic, "
    "uncertain, or should be improved. An empty comment means skip. "
    "No technical terms. Do not prefix with the clause number."
)
_OLD_CONVERGENCE_SV = (
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
    "- Varje inkommande observation_id ska ingå i exakt en issue.\n\n"
    "Avsnitt: {section_heading}\n\n"
    "Batch:\n{batch_text}\n\n"
    "Observationer:\n{observations}\n\n"
    "Returnera issues med observation_ids, paragraph_index, "
    "supporting_expert_ids, kommentar och has_dissensus."
)
_OLD_CONVERGENCE_EN = (
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
    "- Every incoming observation_id must appear in exactly one issue.\n\n"
    "Section: {section_heading}\n\n"
    "Batch:\n{batch_text}\n\n"
    "Observations:\n{observations}\n\n"
    "Return issues with observation_ids, paragraph_index, "
    "supporting_expert_ids, kommentar, and has_dissensus."
)

_UPDATE_KEYS = (
    "expertgranskning.word.expert.comment",
    "expertgranskning.word.comment_convergence",
)
_NEW_KEY = "expertgranskning.word.structured_retry"


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
    for key in _UPDATE_KEYS:
        defaults = _field(key)["defaults"]
        _update_defaults(
            conn,
            key,
            sv=defaults["sv"],
            en=defaults["en"],
            nb=defaults["nb"],
        )

    exists = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    ).fetchone()
    if exists is not None:
        return
    field = _field(_NEW_KEY)
    labels = field["label"]
    hints = field["hint"]
    defaults = field["defaults"]
    conn.execute(
        sa.text(
            "INSERT INTO prompt_fields ("
            "key, modules, section, label_sv, label_en, hint_sv, hint_en, "
            "default_sv, default_en, default_nb, active"
            ") VALUES ("
            ":key, :modules, :section, :label_sv, :label_en, :hint_sv, :hint_en, "
            ":default_sv, :default_en, :default_nb, 1"
            ")"
        ).bindparams(
            key=_NEW_KEY,
            modules=json.dumps(modules_for_prompt_key(_NEW_KEY)),
            section=field["section"],
            label_sv=labels["sv"],
            label_en=labels["en"],
            hint_sv=hints["sv"],
            hint_en=hints["en"],
            default_sv=defaults["sv"],
            default_en=defaults["en"],
            default_nb=defaults["nb"],
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    ).fetchone()
    if field_id is not None:
        conn.execute(
            sa.text(
                "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
            ).bindparams(field_id=field_id[0])
        )
        conn.execute(
            sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
        )
    _update_defaults(
        conn,
        "expertgranskning.word.expert.comment",
        sv=_OLD_COMMENT_SV,
        en=_OLD_COMMENT_EN,
        nb=_OLD_COMMENT_SV,
    )
    _update_defaults(
        conn,
        "expertgranskning.word.comment_convergence",
        sv=_OLD_CONVERGENCE_SV,
        en=_OLD_CONVERGENCE_EN,
        nb=_OLD_CONVERGENCE_SV,
    )
