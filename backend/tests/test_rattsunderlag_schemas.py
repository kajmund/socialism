from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.report.rattsutredning import compute_sourcing_status
from app.services.rattsunderlag.attribution import apply_attribution, known_source_ids
from app.services.rattsunderlag.schemas import LagtextRef, PraxisRef, RattsunderlagResult


def test_lagtext_requires_sfs_id():
    with pytest.raises(ValidationError, match="sfs_id"):
        LagtextRef(sfs_id="  ", rubrik="x")


def test_praxis_requires_referens():
    with pytest.raises(ValidationError, match="referens"):
        PraxisRef(referens="", instans="HD")


def test_sourcing_status_from_hits_not_llm():
    law = [LagtextRef(sfs_id="2016:1145", rubrik="LOU")]
    assert (
        compute_sourcing_status(lagtext=[], praxis=[], forarbeten=[]) == "no_sources_found"
    )
    assert compute_sourcing_status(lagtext=law, praxis=[], forarbeten=[]) == "complete"
    assert (
        compute_sourcing_status(lagtext=law, praxis=[], forarbeten=[], unanswered=["x"])
        == "partial"
    )


def test_attribution_strips_invented_refs():
    law = [LagtextRef(sfs_id="2016:1145", rubrik="LOU", utdrag="likabehandling")]
    known = known_source_ids(lagtext=law, praxis=[], forarbeten=[])
    text, claims, unanswered = apply_attribution(
        "Likabehandling krävs. [[ref:2016:1145]] Fabricerat mål. [[ref:NJA 1999 s. 1]]",
        known,
    )
    assert "NJA 1999 s. 1" not in text
    assert [(row.text, row.source_refs) for row in claims] == [
        ("Likabehandling krävs.", ["2016:1145"])
    ]
    assert unanswered == ["Fabricerat mål."]


def test_result_is_rattsutredning_payload():
    result = RattsunderlagResult(
        fraga="Gäller LOU?",
        lagtext=[LagtextRef(sfs_id="2016:1145")],
        praxis=[],
        forarbeten=[],
        sammanfattning="Ja. [[ref:2016:1145]]",
        sourcing_status="partial",
    )
    payload = result.as_payload()
    assert payload.fraga == result.fraga
    assert payload.lagtext[0].sfs_id == "2016:1145"
