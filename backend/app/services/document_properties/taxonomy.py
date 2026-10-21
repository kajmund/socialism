"""Frozen document-property taxonomy (v1).

Deterministic discovery markers. Source of truth is the frozen experiment
taxonomy; do not tune markers from verification results. A change after human
review ships as a new version with separate regression tests.
"""

from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "v1"


@dataclass(frozen=True)
class PropertyClass:
    class_id: str
    label: str
    definition: str
    value_type: str
    positive_markers: tuple[str, ...]
    negative_markers: tuple[str, ...]
    composite_requires: tuple[str, ...]


TAXONOMY: dict[str, PropertyClass] = {
    "governing_law": PropertyClass(
        class_id="governing_law",
        label="Tillämplig rätt",
        definition="The contract states which jurisdiction or law governs it.",
        value_type="jurisdiction",
        positive_markers=(
            "svensk lag",
            "svensk rätt",
            "tillämplig lag",
            "tillämplig rätt",
            "lagval",
            "lag som ska tillämpas",
        ),
        negative_markers=(),
        composite_requires=(),
    ),
    "confidentiality_obligation": PropertyClass(
        class_id="confidentiality_obligation",
        label="Sekretessplikt",
        definition="The contract imposes an operative duty of secrecy or non-disclosure.",
        value_type="boolean",
        positive_markers=(
            "sekretess",
            "tystnadsplikt",
            "konfidentiell information",
            "konfidentiella uppgifter",
            "företagshemligheter",
            "röja",
        ),
        negative_markers=(
            "ingen sekretess",
            "inga sekretess",
            "utan sekretess",
            "ingen tystnadsplikt",
        ),
        composite_requires=(),
    ),
    "termination_notice": PropertyClass(
        class_id="termination_notice",
        label="Uppsägningstid",
        definition="The contract states a notice period or how it may be terminated.",
        value_type="boolean",
        positive_markers=(
            "uppsägningstid",
            "uppsägningstiden",
            "sägas upp",
            "säga upp",
            "sägs upp",
            "uppsägs",
        ),
        negative_markers=(),
        composite_requires=(),
    ),
    "automatic_renewal": PropertyClass(
        class_id="automatic_renewal",
        label="Automatisk förlängning",
        definition="The contract contains a standing tacit or automatic renewal term.",
        value_type="boolean",
        positive_markers=(
            "förlängs automatiskt",
            "automatisk förlängning",
            "förlängs därefter",
            "förlängs avtalet",
            "förlängs det",
        ),
        negative_markers=(
            "förlängs inte",
            "inte automatiskt",
            "förlängs inte automatiskt",
        ),
        composite_requires=(),
    ),
    "liability_limitation": PropertyClass(
        class_id="liability_limitation",
        label="Ansvarsbegränsning",
        definition="The contract caps or excludes damages liability.",
        value_type="boolean",
        positive_markers=(
            "ansvarsbegränsning",
            "ansvar är begränsat",
            "ansvaret är begränsat",
            "begränsat ansvar",
            "indirekt skada",
            "följdskada",
        ),
        negative_markers=(),
        composite_requires=(),
    ),
    "liability_secrecy_carveout": PropertyClass(
        class_id="liability_secrecy_carveout",
        label="Undantag från ansvarsbegränsning vid sekretessbrott",
        definition="A liability limitation does not apply to a breach of secrecy.",
        value_type="boolean",
        positive_markers=(
            "brott mot sekretess",
            "brott mot sekretessåtagandet",
            "brott mot tystnadsplikt",
            "sekretessbrott",
        ),
        negative_markers=(),
        composite_requires=("liability_limitation",),
    ),
    "force_majeure": PropertyClass(
        class_id="force_majeure",
        label="Befrielsegrund vid oförutsedda händelser",
        definition="The contract relieves a party for circumstances beyond its control.",
        value_type="boolean",
        positive_markers=(
            "force majeure",
            "befrielsegrund",
            "befriad från",
            "befrias från",
            "vis major",
            "hinder utanför kontroll",
            "omständigheter utanför partens kontroll",
        ),
        negative_markers=(),
        composite_requires=(),
    ),
    "personal_data_processing": PropertyClass(
        class_id="personal_data_processing",
        label="Personuppgiftsreglering",
        definition="The contract regulates processing of personal data.",
        value_type="boolean",
        positive_markers=(
            "gdpr",
            "dataskyddsförordningen",
            "personuppgift",
            "personuppgifter",
            "dataskydd",
            "personuppgiftsbiträde",
        ),
        negative_markers=(),
        composite_requires=(),
    ),
    "assignment_restriction": PropertyClass(
        class_id="assignment_restriction",
        label="Överlåtelseförbud",
        definition="The contract restricts assignment or transfer of rights.",
        value_type="boolean",
        positive_markers=(
            "överlåtelseförbud",
            "cession",
            "assignment",
            "överlåta",
            "överlåtelse",
            "partsbyte",
        ),
        negative_markers=(),
        composite_requires=(),
    ),
}
