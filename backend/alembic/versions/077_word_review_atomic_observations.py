"""Atomic, perspective-safe Word review observations.

Revision ID: 077_word_review_atomic_observations
Revises: 076_word_review_actor_context
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.services.prompt_catalog import PROMPT_FIELDS

revision: str = "077_word_review_atomic_observations"
down_revision: Union[str, Sequence[str], None] = "076_word_review_actor_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = {
    'expertgranskning.word.moderator.batch': {
        'sv': 'Du är moderator för en expertgranskning av ett Word-dokument. Förstå batchen i dokumentets helhet. Avgör om expertbedömning behövs och formulera i så fall högst två konkreta granskningsfrågor, ordnade efter materialitet och betydelse (viktigast först). Gör inte specialistbedömningen och välj inte vilka experter som ska svara. Använd panelinformationen bara för att formulera relevanta frågor.\n\nVar konservativ. Skapa inte frågor bara för att text finns. Namn, telefon, e-post, kontaktuppgifter, ren metadata och trivial administration ska normalt inte granskas. Identifiera däremot sådant som kräver bedömning: oklarheter, motsägelser, risker, betydelsefulla antaganden, saknad information med faktisk betydelse, potentiella konsekvenser och genomförbarhetsproblem. Det är exempel, inte en domänspecifik checklista.\n\nGranskarens perspektiv (styr needs_review och frågeformulering; det är inte dokumentförfattarens röst):\n{review_context}\n\nAktörskontexten i systemmeddelandet är bindande när perspektivet är känt. Dokumentet kan vara skrivet från en annan partsställning, ett annat mål eller en annan oro än granskarens. Blanda inte ihop dem. Formulera frågor utifrån granskarens svar och aktörskontext, inte från dokumentets implicita ståndpunkt.\n\nPanel:\n{expert_list}\n\nAvsnitt: {section_heading}\n\nDen här batchen:\n{batch_text}\n\nHela dokumentet ligger i systemmeddelandet.\n\nReturnera needs_review, reason och questions. Högst två frågor. Varje fråga ska ha id, paragraph_indexes (bara index från batchen), primary_anchor_paragraph_index (ett av frågans paragraph_indexes), question och why_it_matters. Om needs_review är false: tom questions-lista.',
        'en': "You moderate an expert review of a Word document. Understand the batch in the full document context. Decide whether expert assessment is needed and, if so, write at most two concrete review questions, ordered by materiality and importance (most important first). Do not make the specialist assessment and do not choose which experts should answer. Use the panel information only to formulate relevant questions.\n\nBe conservative. Do not create questions just because text exists. Names, phone numbers, email, contact details, pure metadata, and trivial administration should normally not be reviewed. Do identify things that need judgment: ambiguities, contradictions, risks, material assumptions, missing information that actually matters, potential consequences, and feasibility problems. These are examples, not a domain-specific checklist.\n\nReviewer perspective (governs needs_review and question wording; this is not the document author's voice):\n{review_context}\n\nActor context in the system message is binding when perspective is known. The document may be written from a different party, objective, or concern than the reviewer's. Do not conflate them. Formulate questions from the reviewer answers and actor context, not from the document's implied standpoint.\n\nPanel:\n{expert_list}\n\nSection: {section_heading}\n\nThis batch:\n{batch_text}\n\nThe full document is in the system message.\n\nReturn needs_review, reason, and questions. At most two questions. Each question must have id, paragraph_indexes (only indexes from the batch), primary_anchor_paragraph_index (one of that question's paragraph_indexes), question, and why_it_matters. If needs_review is false: empty questions list.",
    },
    'expertgranskning.word.expert.comment': {
        'sv': 'Din roll: {label}\nProfil: {profile}\n\nHela dokumentet ligger i systemmeddelandet.\n\nAvsnitt: {section_heading}\nKlausulnummer (internt): {list_string}\n\nGranskningsfråga: {question}\nVarför det spelar roll: {why_it_matters}\n\nTillåtna stycken (välj exakt ett ankare): {allowed_paragraph_indexes}\n\nRelevant dokumenttext:\n{paragraph_text}\n\nGe en konkret expertbedömning. Återberätta inte texten och kommentera inte enbart att information finns. Förklara vad som är relevant, problematiskt, osäkert eller bör förbättras. Tom kommentar betyder att du hoppar över. Inga tekniska termer. Prefixera inte med klausulnummer.\n\nSätt anchor_paragraph_index till det enda stycke bland de tillåtna som bär observationen. Gissa inte ett annat stycke.\n\nFölj aktörskontexten i systemmeddelandet. När perspektivet är känt: vänd rekommendationer till användarens roll. Du får peka ut motpartens eller mottagarens starkaste argument, men märk dem som deras perspektiv. Gör inte om dem till råd till användaren. Dokumentets röst är inte granskarens röst. Saklig kritik som talar mot användarens position är tillåten och krävs när den är befogad. Detta är perspektivstyrning, inte partsadvocacy. När perspektivet är okänt: skriv neutralt och hitta inte på en sida. Vänd inte på dokumentfakta. Externa antaganden ska märkas som antaganden.',
        'en': "Your role: {label}\nProfile: {profile}\n\nThe full document is in the system message.\n\nSection: {section_heading}\nClause number (internal): {list_string}\n\nReview question: {question}\nWhy it matters: {why_it_matters}\n\nAllowed paragraphs (choose exactly one anchor): {allowed_paragraph_indexes}\n\nRelevant document text:\n{paragraph_text}\n\nGive a concrete expert assessment. Do not retell the text and do not only note that the information exists. Explain what is relevant, problematic, uncertain, or should be improved. An empty comment means skip. No technical terms. Do not prefix with the clause number.\n\nSet anchor_paragraph_index to the single allowed paragraph that most directly supports the observation. Do not guess another paragraph.\n\nFollow the actor context in the system message. When perspective is known: address recommendations to the user's role. You may identify the counterpart or audience's strongest argument, but label it as their perspective. Do not turn it into advice to the user. Document voice is not reviewer voice. Factual criticism that is adverse to the user's position is allowed and required when warranted. This is perspective control, not advocacy. When perspective is unknown: stay neutral and do not invent a side. Do not reverse document facts. Phrase external assumptions as assumptions.",
    },
    'expertgranskning.word.comment_convergence': {
        'sv': 'Du konsoliderar expertkommentarer till Word-granskningsissues. Deduplicera observationer/issues, inte experter. Komprimera konvergens. Bevara faktisk dissensus. Skriv korta marginalkommentarer och bedöm vad som ska visas.\n\nRegler:\n- Samma kärnrisk eller samma observation från flera experter blir EN issue och EN Word-kommentar. Lista supporting_expert_ids för alla som stödjer den.\n- Samma expert ska inte ge två nästan identiska kommentarer på närliggande stycken för samma issue. Välj det mest specifika textankaret (konkret klausulrad, inte bara inledningsmeningen).\n- short_comment är texten i Word-marginalen: 1–3 hela meningar. Säg vad som är problemet och, när det är relevant, vad användaren bör överväga. Skriv färdiga meningar. Klipp inte av mitt i en mening. Upprepa inte hela resonemanget från explanation.\n- explanation är den fullständiga motiveringen. Den syns inte i marginalen.\n- Syntetisera perspektiven i short_comment och explanation utan att upprepa dem. Juridisk, finansiell och operativ betydelse får rymmas i samma issue när kärnobservationen är densamma.\n- Dissensus får aldrig dedupliceras bort. Olika bedömningar eller rekommendationer ska bli separata issues (has_dissensus=true på var och en) eller en issue med has_dissensus=true där oenigheten är explicit. Hitta aldrig på falsk konsensus. Exempel: en expert tycker att dröjsmålsränta +15 procentenheter är acceptabelt och en annan vill sänka den - båda perspektiven måste överleva. Märk inte genuin oenighet som overlap.\n- materiality: high om issuen väsentligt påverkar dokumentet eller uppgiften, medium om den har tydlig men begränsad betydelse, low om den är marginell eller kosmetisk.\n- actionability: actionable om användaren kan ändra, förhandla, verifiera, förtydliga eller besluta något. informational om det bara är en iakttagelse utan användbar åtgärd.\n- novelty: new om issuen tillför något som inte redan täcks av en annan issue i samma svar. overlap om den redan täcks tillräckligt av en närliggande eller relaterad issue.\n- should_materialize=true bara när issuen är värd en Word-kommentar: tillräckligt materiell, åtgärdbar och ny. En i övrigt giltig observation ska inte visas om den inte spelar roll för användarens granskningsavsikt. Använd inte ett fast maxtak. Bedöm varje issue för sig. Reglerna är dokumentgeneriska: CV, avtal, utredning, upphandling med mera.\n- Följ aktörskontexten i systemmeddelandet när du bedömer materiality, actionability och should_materialize och när du formulerar short_comment. Bevara perspektivet i de inkommande observationerna. Vänd inte ett korrekt orienterat råd till motparten. När perspektivet är känt: vänd rekommendationer till användarens roll. När det är okänt: skriv neutralt och hitta inte på en sida. Vänd inte på dokumentfakta. Märk externa antaganden som antaganden.\n- Varje inkommande observation_id ska ingå i exakt en issue.\n- paragraph_index måste vara ett ankare som redan finns på de grupperade observationerna. Hitta inte på ett annat stycke.\n\nAvsnitt: {section_heading}\n\nBatch:\n{batch_text}\n\nObservationer:\n{observations}\n\nReturnera issues med observation_ids, paragraph_index, supporting_expert_ids, short_comment, explanation, materiality, actionability, novelty, should_materialize och has_dissensus.',
        'en': "You consolidate expert comments into Word review issues. Deduplicate observations/issues, not experts. Compress convergence. Preserve actual dissensus. Write concise margin comments and judge what should be surfaced.\n\nRules:\n- The same core risk or observation from several experts becomes ONE issue and ONE Word comment. List supporting_expert_ids for everyone who supports it.\n- The same expert must not get two nearly identical comments on nearby paragraphs for the same issue. Choose the most specific text anchor (the concrete clause line, not just the introductory sentence).\n- short_comment is the Word margin text: 1-3 complete sentences. State the issue and, where appropriate, the action the user should consider. Write finished sentences. Do not cut a sentence short. Do not repeat the full reasoning already in explanation.\n- explanation is the fuller reasoning. It does not appear in the margin.\n- Synthesize the perspectives in short_comment and explanation without repeating them. Legal, financial, and operational meaning may live in the same issue when the core observation is the same.\n- Dissensus must never be deduplicated away. Different assessments or recommendations must become separate issues (has_dissensus=true on each) or one issue with has_dissensus=true that states the disagreement explicitly. Never invent false consensus. Example: one expert finds default interest of +15 percentage points acceptable and another wants it lowered - both perspectives must survive. Do not mark genuine disagreement as overlap.\n- materiality: high if the issue materially affects the document or task, medium if it has clear but limited importance, low if it is marginal or cosmetic.\n- actionability: actionable if the user can change, negotiate, verify, clarify, or decide something. informational if it is only an observation without a useful next step.\n- novelty: new if the issue adds something not already covered by another issue in the same response. overlap if it is already adequately covered by a nearby or related issue.\n- should_materialize=true only when the issue deserves a Word comment: material enough, actionable, and new. A generally valid observation must not be surfaced if it does not matter for the user's review intent. Do not use a fixed maximum. Judge each issue on its own. The rules are document-generic: CVs, contracts, investigations, procurement material, and similar.\n- Follow the actor context in the system message when judging materiality, actionability, and should_materialize and when writing short_comment. Preserve the perspective of incoming observations. Do not flip a correctly oriented recommendation to the counterpart. When perspective is known: address recommendations to the user's role. When it is unknown: stay neutral and do not invent a side. Do not reverse document facts. Mark external assumptions as assumptions.\n- Every incoming observation_id must appear in exactly one issue.\n- paragraph_index must be an anchor already present on the grouped observations. Do not invent another paragraph.\n\nSection: {section_heading}\n\nBatch:\n{batch_text}\n\nObservations:\n{observations}\n\nReturn issues with observation_ids, paragraph_index, supporting_expert_ids, short_comment, explanation, materiality, actionability, novelty, should_materialize, and has_dissensus.",
    },
}


_UPDATE_KEYS = tuple(OLD)


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
        field = _field(key)
        defaults = field["defaults"]
        _update_defaults(
            conn,
            key,
            sv=defaults["sv"],
            en=defaults["en"],
            nb=defaults["nb"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key, texts in OLD.items():
        _update_defaults(
            conn,
            key,
            sv=texts["sv"],
            en=texts["en"],
            nb=texts["sv"],
        )
