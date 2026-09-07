from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.report.rattsutredning import compute_sourcing_status
from app.services.rattsunderlag.attribution import (
    apply_attribution,
    known_source_ids,
    split_sentences,
)
from app.services.rattsunderlag.schemas import (
    ForarbeteRef,
    LagtextRef,
    PraxisRef,
    RattsunderlagResult,
)


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
    assert "[[ref:" not in text
    assert [(row.text, row.source_refs) for row in claims] == [
        ("Likabehandling krävs.", ["2016:1145"])
    ]
    assert unanswered == ["Fabricerat mål."]


def test_attribution_keeps_legal_abbreviations_with_their_markers():
    law = [LagtextRef(sfs_id="2016:1145", rubrik="LOU")]
    praxis = [PraxisRef(referens="NJA 2018 s. 723", instans="HD")]
    travaux = [ForarbeteRef(referens="prop. 2015/16:195", titel="Nytt ramverk")]
    known = known_source_ids(lagtext=law, praxis=praxis, forarbeten=travaux)
    text, claims, unanswered = apply_attribution(
        "Enligt 4 kap. 1 § LOU ska myndigheten behandla leverantörer lika. "
        "[[ref:2016:1145]] Detta följer av prop. 2015/16:195. "
        "[[ref:prop. 2015/16:195]] Se även NJA 2018 s. 723. [[ref:NJA 2018 s. 723]] "
        "Ett påstående utan källa.",
        known,
    )
    assert "[[ref:" not in text
    assert unanswered == ["Ett påstående utan källa."]
    assert [row.source_refs for row in claims] == [
        ["2016:1145"],
        ["prop. 2015/16:195"],
        ["NJA 2018 s. 723"],
    ]
    assert claims[0].text.startswith("Enligt 4 kap. 1 §")
    assert "prop. 2015/16:195" in claims[1].text
    assert "NJA 2018 s. 723" in claims[2].text


def test_split_sentences_does_not_break_on_kap_prop_sida():
    units = split_sentences(
        "Enligt 4 kap. 1 § LOU ska myndigheten behandla leverantörer lika. "
        "[[ref:2016:1145]] Se NJA 2018 s. 723 och prop. 2015/16:195."
    )
    assert len(units) == 2
    assert units[0].startswith("Enligt 4 kap. 1 §")
    assert units[0].endswith("[[ref:2016:1145]]")
    assert "prop. 2015/16:195" in units[1]


def test_result_is_rattsutredning_payload():
    result = RattsunderlagResult(
        fraga="Gäller LOU?",
        lagtext=[LagtextRef(sfs_id="2016:1145")],
        praxis=[],
        forarbeten=[],
        sammanfattning="Ja.",
        sourcing_status="partial",
    )
    payload = result.as_payload()
    assert payload.fraga == result.fraga
    assert payload.lagtext[0].sfs_id == "2016:1145"
