from overgraph_ingest.coverage.ability_review import (
    DISCOVERY_REGRESSIONS,
    HYPOTHESIS_A,
    HYPOTHESIS_B,
    LIVE_PATH,
    freeze_review_baseline,
    review_payload,
)
from overgraph_ingest.coverage.chain_contract import CITATION_RE, EXCEPTION_RE
from overgraph_ingest.coverage.clause_resolve import NOTHING_LIMITS_RE, parse_citations
from overgraph_ingest.coverage.proof_logic import classify_predication
from overgraph_ingest.coverage.v3 import run_coverage_v3
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_ability_review_baseline,
)

B_SOURCES = {
    "avtal_118.docx": "5.4\tInget i denna punkt ska begränsa parts ansvar för brott mot artikel 4.\n",
    "avtal_125.docx": "VIII.4\tBegränsningen i punkt VIII.2 gäller inte för ansvar vid brott mot avsnitt VI.\n",
    "avtal_141.docx": "8.3\tBegränsningen i klausul 8.1 gäller inte för ansvar vid brott mot klausul 6.\n",
    "avtal_153.docx": "6.3\tBegränsningen i klausul 6.1 gäller inte för ansvar vid brott mot klausul 5.\n",
    "avtal_179.docx": "5.3\tInget i denna punkt ska begränsa parts ansvar för brott mot klausul 7.\n",
}

A_OMFATTAR = (
    "6.3\tBegränsningen i denna punkt omfattar inte skada till följd av brott "
    "mot sekretessåtagandet och inte heller skada som vållats uppsåtligen "
    "eller av grov vårdslöshet.\n"
)


def test_review_splits_a_and_keeps_b_as_one_gap() -> None:
    assert HYPOTHESIS_A["is_one_construction"] is False
    constructions = HYPOTHESIS_A["constructions"]
    assert len(constructions["omfattar_inte"]) == 5
    assert constructions["higher_cap"] == ["avtal_157.docx"]
    assert constructions["double_negation"] == ["avtal_193.docx"]
    assert HYPOTHESIS_A["table_count"] == 7
    assert HYPOTHESIS_B["is_one_construction"] is True
    assert HYPOTHESIS_B["count"] == 5
    assert HYPOTHESIS_B["source_relation_already_holds"] is True
    assert DISCOVERY_REGRESSIONS == (
        "avtal_135.docx",
        "avtal_159.docx",
        "avtal_168.docx",
    )


def test_b_sources_are_unparsed_citations_with_existing_relation() -> None:
    for text in B_SOURCES.values():
        assert not CITATION_RE.search(text)
        assert parse_citations(text) == ()
        assert bool(EXCEPTION_RE.search(text) or NOTHING_LIMITS_RE.search(text))


def test_predication_model_does_not_admit_omfattar_inte() -> None:
    assert classify_predication(A_OMFATTAR) == "undecided"
    assert HYPOTHESIS_A["predication_model_ready"] is False
    assert "EXCEPTION_RE" in HYPOTHESIS_A["do_not_expand"]
    assert "LINK_RE" in HYPOTHESIS_A["do_not_expand"]


def test_live_path_is_not_coverage_v3() -> None:
    assert LIVE_PATH == (
        "chain_contract.assess_chain",
        "clause_resolve.assess_with_clauses",
        "anaphor_resolve.assess_with_anaphors",
    )
    assert run_coverage_v3.__module__ == "overgraph_ingest.coverage.v3"
    assert RETRIEVAL_CONCLUSIONS["ability_review_does_not_start_next_ability"] is True
    assert RETRIEVAL_CONCLUSIONS["previous_quality_reference"] == "19/53"
    assert RETRIEVAL_CONCLUSIONS["latest_quality_reference"] == "24/53"


def test_review_baseline() -> None:
    frozen = load_ability_review_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["does_not_start_next_ability"] is True
    assert frozen["headline"]["hypothesis_a"]["is_one_construction"] is False
    assert frozen["headline"]["hypothesis_b"]["count"] == 5
    payload = review_payload()
    assert payload["quality_reference"]["true_support"] == 19
    assert freeze_review_baseline(payload)["id"] == "phase2-ability-review-v1"
