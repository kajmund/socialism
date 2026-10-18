"""Configurable document-type taxonomy. Principal function, not clauses."""

from __future__ import annotations

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

TYPE_LABELS = {
    EMPLOYMENT: "Anställningsavtal",
    CONSULTING: "Konsultavtal",
    NDA: "Sekretessavtal",
    DPA: "Personuppgiftsbiträdesavtal",
    SUPPLY: "Leveransavtal",
    LEASE: "Hyresavtal",
    TERMINATION: "Överenskommelse om anställningens upphörande",
    OTHER: "Annat",
}

TYPE_CRITERIA = {
    EMPLOYMENT: (
        "The document's principal function is to create or govern an employment. "
        "Supplements about working time, bonus, car, or IT equipment are not this type."
    ),
    CONSULTING: (
        "The document's principal function is an independent professional assignment. "
        "Not employment, and not a contract whose main object is delivering goods or a finished system."
    ),
    NDA: (
        "The document's principal function is a stand-alone duty of secrecy. "
        "A consulting or employment agreement that contains a secrecy clause is not an NDA."
    ),
    DPA: (
        "The document's principal function is a data-processing agreement under GDPR. "
        "A main contract that only mentions data protection is not a DPA."
    ),
    SUPPLY: (
        "The document's principal function is to supply goods or a contracted deliverable "
        "to a customer, or to buy such a supply. Includes framework service delivery, "
        "project delivery, SaaS, hosting, and support."
    ),
    LEASE: (
        "The document's principal function is to let premises, land, equipment, or a vehicle. "
        "Coworking that is a service package without exclusive premises is not this type."
    ),
    TERMINATION: (
        "The document's principal function is to end an employment, by notice or by agreement. "
        "A later settlement of a dispute about a past termination is not this type."
    ),
    OTHER: (
        "The document's principal function is none of the types above."
    ),
}


def require_type(document_type: str) -> str:
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"unknown document type: {document_type}")
    return document_type
