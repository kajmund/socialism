"""Unit tests for deterministic document-type classification."""

from app.services.document_find.classify import classify_document
from app.services.document_find.taxonomy import (
    CONSULTING,
    DPA,
    EMPLOYMENT,
    LEASE,
    NDA,
    OTHER,
    SUPPLY,
    type_from_user_phrase,
)


def test_classify_lease_from_title():
    assert classify_document(title="Hyresavtal Storgatan 1") == LEASE


def test_classify_employment_from_opening():
    assert classify_document(
        title="Avtal",
        opening="Detta anställningsavtal gäller tillsvidareanställning.",
    ) == EMPLOYMENT


def test_classify_unknown_is_other():
    assert classify_document(title="Anteckningar från möte") == OTHER


def test_classify_dpa_from_label():
    assert classify_document(title="Personuppgiftsbiträdesavtal") == DPA


def test_type_from_user_phrase_hyresavtal():
    assert type_from_user_phrase("Visa alla hyresavtal.") == LEASE


def test_type_from_user_phrase_synonyms():
    assert type_from_user_phrase("andrahandsuthyrning") == LEASE
    assert type_from_user_phrase("arrendeavtal för åkermark") == LEASE
    assert type_from_user_phrase("lägenhetsarrende") == LEASE
    assert type_from_user_phrase("ramavtal med leverantör") == SUPPLY
    assert type_from_user_phrase("uppdragsavtal") == CONSULTING
    assert type_from_user_phrase("provanställning") == EMPLOYMENT
    assert type_from_user_phrase("databehandlingsavtal") == DPA
    assert type_from_user_phrase("NDA") == NDA


def test_type_from_user_phrase_incident_query():
    query = "hyresavtal lokal bostad andrahandsuthyrning arrendeavtal lägenhetsarrende"
    assert type_from_user_phrase(query) == LEASE
