"""Add review-intent prompt and let Word review follow it.

Revision ID: 070_review_intent
Revises: 069_word_actions
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_defaults import modules_for_prompt_key

revision: str = "070_review_intent"
down_revision: Union[str, Sequence[str], None] = "069_word_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_KEY = "panel.review_intent"
_UPDATE_KEYS = (
    "expertgranskning.word.moderator.batch",
    "expertgranskning.word.expert.comment",
    "expertgranskning.word.comment_convergence",
)

_OLD_BATCH_SV = 'Du är moderator för en expertgranskning av ett Word-dokument. Förstå batchen i dokumentets helhet. Avgör om expertbedömning behövs och formulera i så fall konkreta granskningsfrågor. Gör inte specialistbedömningen och välj inte vilka experter som ska svara. Använd panelinformationen bara för att formulera relevanta frågor.\n\nVar konservativ. Skapa inte frågor bara för att text finns. Namn, telefon, e-post, kontaktuppgifter, ren metadata och trivial administration ska normalt inte granskas. Identifiera däremot sådant som kräver bedömning: oklarheter, motsägelser, risker, betydelsefulla antaganden, saknad information med faktisk betydelse, potentiella konsekvenser och genomförbarhetsproblem. Det är exempel, inte en domänspecifik checklista.\n\nPanel:\n{expert_list}\n\nAvsnitt: {section_heading}\n\nDen här batchen:\n{batch_text}\n\nHela dokumentet ligger i systemmeddelandet.\n\nReturnera needs_review, reason och questions. Varje fråga ska ha id, paragraph_indexes (bara index från batchen), question och why_it_matters. Om needs_review är false: tom questions-lista.'
_OLD_BATCH_EN = 'You moderate an expert review of a Word document. Understand the batch in the full document context. Decide whether expert assessment is needed and, if so, write concrete review questions. Do not make the specialist assessment and do not choose which experts should answer. Use the panel information only to formulate relevant questions.\n\nBe conservative. Do not create questions just because text exists. Names, phone numbers, email, contact details, pure metadata, and trivial administration should normally not be reviewed. Do identify things that need judgment: ambiguities, contradictions, risks, material assumptions, missing information that actually matters, potential consequences, and feasibility problems. These are examples, not a domain-specific checklist.\n\nPanel:\n{expert_list}\n\nSection: {section_heading}\n\nThis batch:\n{batch_text}\n\nThe full document is in the system message.\n\nReturn needs_review, reason, and questions. Each question must have id, paragraph_indexes (only indexes from the batch), question, and why_it_matters. If needs_review is false: empty questions list.'
_OLD_COMMENT_SV = 'Din roll: {label}\nProfil: {profile}\n\nHela dokumentet ligger i systemmeddelandet.\n\nAvsnitt: {section_heading}\nKlausulnummer (internt): {list_string}\n\nGranskningsfråga: {question}\nVarför det spelar roll: {why_it_matters}\n\nTillåtna stycken (välj exakt ett ankare): {allowed_paragraph_indexes}\n\nRelevant dokumenttext:\n{paragraph_text}\n\nGe en konkret expertbedömning. Återberätta inte texten och kommentera inte enbart att information finns. Förklara vad som är relevant, problematiskt, osäkert eller bör förbättras. Tom kommentar betyder att du hoppar över. Inga tekniska termer. Prefixera inte med klausulnummer.\n\nSätt anchor_paragraph_index till det enda stycke bland de tillåtna som bär observationen. Gissa inte ett annat stycke.\n\nGranskande part är okänd. Använd dokumentets partsbeteckningar (Leverantören, Beställaren, Kunden, Konsulten) och skriv inte för er som kund eller du som kund. Anta inte vilken sida användaren är. Vänd inte på dokumentfakta. Externa antaganden ska märkas som antaganden.'
_OLD_COMMENT_EN = "Your role: {label}\nProfile: {profile}\n\nThe full document is in the system message.\n\nSection: {section_heading}\nClause number (internal): {list_string}\n\nReview question: {question}\nWhy it matters: {why_it_matters}\n\nAllowed paragraphs (choose exactly one anchor): {allowed_paragraph_indexes}\n\nRelevant document text:\n{paragraph_text}\n\nGive a concrete expert assessment. Do not retell the text and do not only note that the information exists. Explain what is relevant, problematic, uncertain, or should be improved. An empty comment means skip. No technical terms. Do not prefix with the clause number.\n\nSet anchor_paragraph_index to the single allowed paragraph that most directly supports the observation. Do not guess another paragraph.\n\nThe reviewing party is unknown. Use the document's party labels (Supplier, Customer, Buyer, Consultant) and do not write for you as the customer or you as the client. Do not assume which side the user is on. Do not reverse document facts. Phrase external assumptions as assumptions."
_OLD_COMMENT_CONVERGENCE_SV = 'Du konsoliderar expertkommentarer till Word-kommentarer. Deduplicera observationer/issues, inte experter. Komprimera konvergens. Bevara faktisk dissensus.\n\nRegler:\n- Samma kärnrisk eller samma observation från flera experter blir EN issue och EN Word-kommentar. Lista supporting_expert_ids för alla som stödjer den.\n- Samma expert ska inte ge två nästan identiska kommentarer på närliggande stycken för samma issue. Välj det mest specifika textankaret (konkret klausulrad, inte bara inledningsmeningen).\n- Syntetisera perspektiven i kommentar-fältet utan att upprepa dem. Juridisk, finansiell och operativ betydelse får rymmas i samma kommentar när kärnobservationen är densamma.\n- Dissensus får aldrig dedupliceras bort. Olika bedömningar eller rekommendationer ska bli separata issues (has_dissensus=true på var och en) eller en issue med has_dissensus=true där oenigheten är explicit. Hitta aldrig på falsk konsensus. Exempel: en expert tycker att dröjsmålsränta +15 procentenheter är acceptabelt och en annan vill sänka den - båda perspektiven måste överleva.\n- Varje inkommande observation_id ska ingå i exakt en issue.\n- paragraph_index måste vara ett ankare som redan finns på de grupperade observationerna. Hitta inte på ett annat stycke.\n- Granskande part är okänd. Använd dokumentets partsbeteckningar. Skriv inte för er som kund eller du som kund. Vänd inte på dokumentfakta. Märk externa antaganden som antaganden.\n\nAvsnitt: {section_heading}\n\nBatch:\n{batch_text}\n\nObservationer:\n{observations}\n\nReturnera issues med observation_ids, paragraph_index, supporting_expert_ids, kommentar och has_dissensus.'
_OLD_COMMENT_CONVERGENCE_EN = "You consolidate expert comments into Word comments. Deduplicate observations/issues, not experts. Compress convergence. Preserve actual dissensus.\n\nRules:\n- The same core risk or observation from several experts becomes ONE issue and ONE Word comment. List supporting_expert_ids for everyone who supports it.\n- The same expert must not get two nearly identical comments on nearby paragraphs for the same issue. Choose the most specific text anchor (the concrete clause line, not just the introductory sentence).\n- Synthesize the perspectives in kommentar without repeating them. Legal, financial, and operational meaning may live in the same comment when the core observation is the same.\n- Dissensus must never be deduplicated away. Different assessments or recommendations must become separate issues (has_dissensus=true on each) or one issue with has_dissensus=true that states the disagreement explicitly. Never invent false consensus. Example: one expert finds default interest of +15 percentage points acceptable and another wants it lowered - both perspectives must survive.\n- Every incoming observation_id must appear in exactly one issue.\n- paragraph_index must be an anchor already present on the grouped observations. Do not invent another paragraph.\n- The reviewing party is unknown. Use the document's party labels. Do not write for you as the customer or you as the client. Do not reverse document facts. Mark external assumptions as assumptions.\n\nSection: {section_heading}\n\nBatch:\n{batch_text}\n\nObservations:\n{observations}\n\nReturn issues with observation_ids, paragraph_index, supporting_expert_ids, kommentar, and has_dissensus."


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
    _update_defaults(
        conn,
        "expertgranskning.word.moderator.batch",
        sv=_OLD_BATCH_SV,
        en=_OLD_BATCH_EN,
        nb=_OLD_BATCH_SV,
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
        sv=_OLD_COMMENT_CONVERGENCE_SV,
        en=_OLD_COMMENT_CONVERGENCE_EN,
        nb=_OLD_COMMENT_CONVERGENCE_SV,
    )
    field_id = conn.execute(
        sa.text("SELECT id FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    ).fetchone()
    if field_id is None:
        return
    conn.execute(
        sa.text(
            "DELETE FROM prompt_overrides WHERE prompt_field_id = :field_id"
        ).bindparams(field_id=field_id[0])
    )
    conn.execute(
        sa.text("DELETE FROM prompt_fields WHERE key = :key").bindparams(key=_NEW_KEY)
    )
