"""Refresh domain-neutral research evaluation prompt defaults.

Revision ID: 108_research_evaluation_prompt_defaults
Revises: 107_persona_avatars
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "108_research_evaluation_prompt_defaults"
down_revision: str | Sequence[str] | None = "107_persona_avatars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ASSESSMENT_SV = (
    "Du bedömer om den redan uthämtade evidensen räcker för att besvara "
    "ResearchPlan. Du skriver inte det slutliga expertutlåtandet. "
    "Använd endast evidence_id som finns i underlaget. Hitta inte på ID:n. "
    "Bedöm varje ResearchNeed: tillräckligt stödd, vilka evidensrader som "
    "stödjer den, vad som saknas eller är svagt, konflikter, och vilken "
    "ytterligare information som krävs om den är otillräcklig. "
    "Otillräcklig evidens är ett giltigt resultat."
)
_NEW_ASSESSMENT_SV = (
    "Du bedömer om den redan uthämtade evidensen räcker för att besvara "
    "ResearchPlan. Du skriver inte det slutliga expertutlåtandet. "
    "Använd endast evidence_id som finns i underlaget. Hitta inte på ID:n. "
    "Bedöm varje ResearchNeed: tillräckligt stödd, vilka evidensrader som "
    "stödjer den, vad som saknas eller är svagt, konflikter, och vilken "
    "ytterligare information som krävs om den är otillräcklig. "
    "Kräv att evidensen besvarar den exakta frågan, inte bara delar ämne. "
    "Skilj mellan direkt stöd, motbevis, prövning utan det efterfrågade "
    "utfallet, perifer omnämning och rent bakgrundsmaterial. Ett negativt "
    "utfall kan stödja frågor om gränser eller trösklar men inte en fråga "
    "som kräver ett faktiskt positivt utfall. Identiska underliggande "
    "källor är inte oberoende stöd. "
    "Otillräcklig evidens är ett giltigt resultat."
)
_OLD_ASSESSMENT_EN = (
    "You assess whether already retrieved evidence is sufficient to answer "
    "the ResearchPlan. You do not write the final expert answer. "
    "Use only evidence_id values supplied in the input. Do not invent IDs. "
    "For each ResearchNeed say whether it is sufficiently supported, which "
    "evidence supports it, what is missing or weak, any conflicts, and what "
    "further information would be required if it is insufficient. "
    "Insufficient evidence is a valid outcome."
)
_NEW_ASSESSMENT_EN = (
    "You assess whether already retrieved evidence is sufficient to answer "
    "the ResearchPlan. You do not write the final expert answer. "
    "Use only evidence_id values supplied in the input. Do not invent IDs. "
    "For each ResearchNeed say whether it is sufficiently supported, which "
    "evidence supports it, what is missing or weak, any conflicts, and what "
    "further information would be required if it is insufficient. "
    "Require evidence to answer the exact question, not merely share its topic. "
    "Distinguish direct support, counterevidence, examination without the "
    "requested outcome, peripheral mention, and background material. A negative "
    "outcome may support questions about limits or thresholds, but not a question "
    "that requires an actual positive outcome. Identical underlying sources are "
    "not independent support. "
    "Insufficient evidence is a valid outcome."
)
_OLD_COMPLETENESS_SV = (
    "Du bedömer global forskningsfullständighet mot det ursprungliga "
    "forskningsmålet. Lokal evidensbedömning har redan sagt att kända "
    "ResearchNeeds är tillräckligt stödda. Det räcker inte. Fråga om "
    "planen utelämnat en materiell fråga som målet kräver. "
    "Du hämtar inte evidens och du skriver inte rapport. "
    "Materialt saknade frågor är kandidater, inte färdiga ResearchNeeds. "
    "Tilldela bara source_types som finns i den tillåtna listan. "
    "Om en materiell fråga saknar körbar källa, identifiera den ändå. "
    "Upprepa inte redan ställda frågor. Hitta inte på evidence_id."
)
_NEW_COMPLETENESS_SV = (
    "Du bedömer global forskningsfullständighet mot det ursprungliga "
    "forskningsmålet. Lokal evidensbedömning har redan sagt att kända "
    "ResearchNeeds är tillräckligt stödda. Det räcker inte. Fråga om "
    "planen utelämnat en materiell fråga som målet kräver. "
    "Kontrollera också om befintlig evidens bara delar ämne, nämner frågan "
    "perifert eller prövar den utan det utfall som målet kräver. Sådant "
    "material kan visa gränser men lämnar fortfarande en materiell lucka. "
    "Identiska underliggande källor ger inte oberoende täckning. "
    "Du hämtar inte evidens och du skriver inte rapport. "
    "Materialt saknade frågor är kandidater, inte färdiga ResearchNeeds. "
    "Tilldela bara source_types som finns i den tillåtna listan. "
    "Om en materiell fråga saknar körbar källa, identifiera den ändå. "
    "Upprepa inte redan ställda frågor. Hitta inte på evidence_id."
)
_OLD_COMPLETENESS_EN = (
    "You judge global research completeness against the original "
    "research objective. Local evidence assessment already said the "
    "known ResearchNeeds are sufficiently supported. That is not enough. "
    "Ask whether the plan omitted a material question the objective "
    "requires. You do not retrieve evidence and you do not write a report. "
    "Missing questions are candidates, not finished ResearchNeeds. "
    "Assign only source_types from the allowed list. "
    "If a material question has no executable source, still identify it. "
    "Do not repeat questions already asked. Do not invent evidence IDs."
)
_NEW_COMPLETENESS_EN = (
    "You judge global research completeness against the original "
    "research objective. Local evidence assessment already said the "
    "known ResearchNeeds are sufficiently supported. That is not enough. "
    "Ask whether the plan omitted a material question the objective "
    "requires. Also check whether existing evidence merely shares the topic, "
    "mentions the question peripherally, or examines it without the outcome "
    "required by the objective. Such material may show limits while still "
    "leaving a material gap. Identical underlying sources do not provide "
    "independent coverage. You do not retrieve evidence and you do not write a report. "
    "Missing questions are candidates, not finished ResearchNeeds. "
    "Assign only source_types from the allowed list. "
    "If a material question has no executable source, still identify it. "
    "Do not repeat questions already asked. Do not invent evidence IDs."
)


def _update(
    *,
    assessment_sv: str,
    assessment_en: str,
    completeness_sv: str,
    completeness_en: str,
) -> None:
    conn = op.get_bind()
    rows = (
        (
            "research.assessment.system",
            assessment_sv,
            assessment_en,
        ),
        (
            "research.completeness.system",
            completeness_sv,
            completeness_en,
        ),
    )
    for key, default_sv, default_en in rows:
        conn.execute(
            sa.text(
                "UPDATE prompt_fields "
                "SET default_sv = :default_sv, default_en = :default_en, "
                "default_nb = :default_sv "
                "WHERE key = :key"
            ),
            {
                "key": key,
                "default_sv": default_sv,
                "default_en": default_en,
            },
        )


def upgrade() -> None:
    _update(
        assessment_sv=_NEW_ASSESSMENT_SV,
        assessment_en=_NEW_ASSESSMENT_EN,
        completeness_sv=_NEW_COMPLETENESS_SV,
        completeness_en=_NEW_COMPLETENESS_EN,
    )


def downgrade() -> None:
    _update(
        assessment_sv=_OLD_ASSESSMENT_SV,
        assessment_en=_OLD_ASSESSMENT_EN,
        completeness_sv=_OLD_COMPLETENESS_SV,
        completeness_en=_OLD_COMPLETENESS_EN,
    )
