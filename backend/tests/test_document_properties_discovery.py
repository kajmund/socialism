"""Deterministic discovery proposes typed, source-grounded properties."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.document_properties.discovery import extract_document_properties
from app.services.document_properties.model import (
    POLARITY_NEGATIVE,
    POLARITY_POSITIVE,
    POLARITY_UNCLEAR,
)


@dataclass(frozen=True)
class FakeUnit:
    id: str
    text: str
    document_id: str
    document_version_id: str


def _unit(unit_id: str, text: str) -> FakeUnit:
    return FakeUnit(unit_id, text, "doc-a", "ver-a")


def test_positive_boolean_property_is_proposed():
    properties = extract_document_properties(
        [_unit("tu-1", "Arbetstagaren har tystnadsplikt om företagshemligheter.")]
    )
    confidentiality = next(
        p for p in properties if p.class_id == "confidentiality_obligation"
    )
    assert confidentiality.value is True
    assert confidentiality.polarity == POLARITY_POSITIVE
    assert confidentiality.source_unit_keys == ("tu-1",)
    assert confidentiality.document_id == "doc-a"


def test_negative_marker_yields_negative_property():
    properties = extract_document_properties(
        [_unit("tu-1", "Det finns ingen sekretess mellan parterna.")]
    )
    confidentiality = next(
        p for p in properties if p.class_id == "confidentiality_obligation"
    )
    assert confidentiality.value is False
    assert confidentiality.polarity == POLARITY_NEGATIVE


def test_jurisdiction_value_is_extracted():
    properties = extract_document_properties(
        [_unit("tu-1", "Tvister avgörs enligt svensk lag.")]
    )
    governing = next(p for p in properties if p.class_id == "governing_law")
    assert governing.value == "Sweden"
    assert governing.polarity == POLARITY_POSITIVE


def test_composite_carveout_is_unclear_without_liability_limitation():
    only_carveout = extract_document_properties(
        [_unit("tu-1", "Begränsningen gäller inte vid brott mot sekretess.")]
    )
    carveout = next(
        p for p in only_carveout if p.class_id == "liability_secrecy_carveout"
    )
    assert carveout.polarity == POLARITY_UNCLEAR
    assert carveout.source_unit_keys == ()

    with_limitation = extract_document_properties(
        [
            _unit("tu-1", "Partens ansvar är begränsat till avtalat belopp."),
            _unit("tu-2", "Begränsningen gäller inte vid brott mot sekretess."),
        ]
    )
    carveout = next(
        p for p in with_limitation if p.class_id == "liability_secrecy_carveout"
    )
    assert carveout.polarity == POLARITY_POSITIVE
    assert carveout.source_unit_keys == ("tu-2",)
