"""Jev verification: SUPPORTED requires a grounded source; errors stay technical."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.document_properties.model import (
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    DocumentProperty,
)
from app.services.document_properties.taxonomy import TAXONOMY
from app.services.document_properties.verification import verify_document_property


@dataclass(frozen=True)
class FakeSection:
    title: str


@dataclass(frozen=True)
class FakeUnit:
    id: str
    text: str
    section: FakeSection | None = None


class FakeJev:
    def __init__(self, verdict: str, source: str):
        self.verdict = verdict
        self.source = source
        self.seen_state: dict | None = None

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.seen_state = state
        return JevSystemOneResult(
            answers={"verdict": {"choice": self.verdict}, "source": {"choice": self.source}},
            model=model,
            latency_ms=1.0,
            input_chars=0,
            usage=JevUsage(),
            raw={},
        )


def _prop() -> DocumentProperty:
    return DocumentProperty(
        class_id="confidentiality_obligation",
        document_id="doc-a",
        document_version_id="ver-a",
        value=True,
        polarity="positive",
        taxonomy_version="v1",
        source_unit_keys=("tu-1",),
    )


def _units() -> list[FakeUnit]:
    return [
        FakeUnit("tu-1", "Arbetstagaren har tystnadsplikt om företagshemligheter.", FakeSection("7. Sekretess")),
    ]


@pytest.mark.asyncio
async def test_supported_with_grounded_source():
    outcome = await verify_document_property(
        FakeJev(SUPPORTED, "tu-1:0"),
        prop=_prop(),
        spec=TAXONOMY["confidentiality_obligation"],
        candidate_units=_units(),
        model="test",
        timeout_seconds=1.0,
    )
    assert outcome.decision == SUPPORTED
    assert outcome.source_unit_key == "tu-1"
    assert outcome.source_valid is True
    assert "tystnadsplikt" in (outcome.supporting_excerpt or "")


@pytest.mark.asyncio
async def test_supported_without_source_is_undecided():
    outcome = await verify_document_property(
        FakeJev(SUPPORTED, "none"),
        prop=_prop(),
        spec=TAXONOMY["confidentiality_obligation"],
        candidate_units=_units(),
        model="test",
        timeout_seconds=1.0,
    )
    assert outcome.decision == UNDECIDED
    assert outcome.source_valid is False


@pytest.mark.asyncio
async def test_unsupported_is_reported():
    outcome = await verify_document_property(
        FakeJev(UNSUPPORTED, "none"),
        prop=_prop(),
        spec=TAXONOMY["confidentiality_obligation"],
        candidate_units=_units(),
        model="test",
        timeout_seconds=1.0,
    )
    assert outcome.decision == UNSUPPORTED


@pytest.mark.asyncio
async def test_invalid_verdict_is_schema_error():
    with pytest.raises(JevClientError):
        await verify_document_property(
            FakeJev("maybe", "none"),
            prop=_prop(),
            spec=TAXONOMY["confidentiality_obligation"],
            candidate_units=_units(),
            model="test",
            timeout_seconds=1.0,
        )


@pytest.mark.asyncio
async def test_evidence_clauses_present_full_text_as_primary():
    jev = FakeJev(SUPPORTED, "tu-1:0")
    await verify_document_property(
        jev,
        prop=_prop(),
        spec=TAXONOMY["confidentiality_obligation"],
        candidate_units=_units(),
        model="test",
        timeout_seconds=1.0,
    )
    clauses = jev.seen_state["evidence_clauses"]
    assert clauses[0]["text"] == "Arbetstagaren har tystnadsplikt om företagshemligheter."
    assert clauses[0]["heading"] == "7. Sekretess"
