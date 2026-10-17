"""Flat document-type taxonomy. Product contract, not experiment import."""

from __future__ import annotations

import re
import unicodedata

TAXONOMY_VERSION = "document-types-v1"

EMPLOYMENT = "employment_agreement"
CONSULTING = "consulting_agreement"
NDA = "nda"
DPA = "dpa"
SUPPLY = "supply_agreement"
LEASE = "lease_agreement"
TERMINATION = "employment_termination_agreement"
OTHER = "other"

DOCUMENT_TYPES = (
    EMPLOYMENT,
    CONSULTING,
    NDA,
    DPA,
    SUPPLY,
    LEASE,
    TERMINATION,
    OTHER,
)

TYPE_LABELS_SV = {
    EMPLOYMENT: "Anställningsavtal",
    CONSULTING: "Konsultavtal",
    NDA: "Sekretessavtal",
    DPA: "Personuppgiftsbiträdesavtal",
    SUPPLY: "Leveransavtal",
    LEASE: "Hyresavtal",
    TERMINATION: "Överenskommelse om anställningens upphörande",
    OTHER: "Annat",
}

NDA_RE = re.compile(r"\bnda\b")

# Pre-folded synonym needles shared by query matching and ingest classification.
# Order matters: first hit wins.
TYPE_NEEDLES: tuple[tuple[tuple[str, ...], str], ...] = (
    ((
        "uppsagningsbesked",
        "avgangsvederlag",
        "overenskommelse om avslut",
        "avslut av anstallning",
        "anstallningens upphorande",
    ), TERMINATION),
    ((
        "personuppgiftsbitradesavtal",
        "databehandlingsavtal",
        "pub-avtal",
        "pub_avtal",
        "pub avtal",
    ), DPA),
    ((
        "anstallningsavtal",
        "tillsvidareanstallning",
        "provanstallning",
        "visstidsanstallning",
        "timanstallning",
        "behovsanstallning",
    ), EMPLOYMENT),
    ((
        "hyresavtal",
        "arrendeavtal",
        "lagenhetsarrende",
        "leasingavtal",
        "parkeringsavtal",
        "andrahandsuthyrning",
    ), LEASE),
    ((
        "konsultavtal",
        "redovisningsuppdrag",
        "byraavtal",
        "uppdragsavtal",
    ), CONSULTING),
    ((
        "leveransavtal",
        "inkopsavtal",
        "ramavtal",
        "saas",
        "hostingavtal",
        "projektavtal",
    ), SUPPLY),
)

def fold_candidate(text: str) -> str:
    """Casefold and strip accents so needles and phrases compare canonically."""
    stripped = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return stripped.replace("_", " ")


_FOLDED_LABEL_TO_TYPE = {
    fold_candidate(label): key for key, label in TYPE_LABELS_SV.items()
}


def require_type(document_type: str) -> str:
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"unknown document type: {document_type}")
    return document_type


def type_from_user_phrase(phrase: str) -> str | None:
    folded = fold_candidate(phrase).strip()
    if folded in _FOLDED_LABEL_TO_TYPE:
        return _FOLDED_LABEL_TO_TYPE[folded]
    for label, key in _FOLDED_LABEL_TO_TYPE.items():
        if label in folded:
            return key
    if NDA_RE.search(folded):
        return NDA
    for needles, document_type in TYPE_NEEDLES:
        if any(needle in folded for needle in needles):
            return document_type
    return None
