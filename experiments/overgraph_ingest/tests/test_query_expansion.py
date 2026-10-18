from pathlib import Path

from overgraph_ingest.coverage.compare import compare_v3_golds
from overgraph_ingest.coverage.experimental import load_experimental_append_baseline
from overgraph_ingest.coverage.run import _golds
from overgraph_ingest.retrieval.expand import (
    APPEND,
    BASELINE,
    EXPANSION_POLICY,
    expansion_for,
    load_expansions,
    query_for,
)
from overgraph_ingest.retrieval.gold import load_gold_suite
from overgraph_ingest.retrieval.search import SearchHit, rrf_fuse

GOLD_DIR = Path(__file__).resolve().parents[1] / "retrieval_gold"


def test_lexicon_covers_every_gold_and_avoids_exact_gold_spans() -> None:
    expansions = load_expansions()
    golds = load_gold_suite(GOLD_DIR)
    assert set(expansions) == {gold.id for gold in golds}
    for gold in golds:
        expansion = expansion_for(gold, expansions)
        assert expansion.terms
        contains = {span.contains for span in gold.relevant_units}
        assert not set(expansion.terms) & contains
        expanded = expansion.append(gold.query)
        assert gold.query in expanded
        for term in expansion.terms:
            if term.casefold() not in gold.query.casefold():
                assert term in expanded


def test_append_skips_terms_already_in_the_query() -> None:
    expansion = load_expansions()["notice-period"]
    query = "Vilka avtal innehåller en uppsägningstid?"
    expanded = expansion.append(query)
    assert expanded.startswith(query)
    assert expanded.count("uppsägningstid") == 1
    assert "ömsesidig uppsägning" in expanded


def test_fuse_keeps_the_better_rank() -> None:
    left = [
        SearchHit(1, "a", 1.0, 20, "d", "a.docx", "sekretess"),
        SearchHit(2, "b", 0.5, 1, "d", "b.docx", "annat"),
    ]
    right = [
        SearchHit(1, "a", 1.0, 2, "d", "a.docx", "sekretess"),
        SearchHit(2, "b", 0.5, 30, "d", "b.docx", "annat"),
    ]
    fused = rrf_fuse([left, right])
    assert fused[0].key == "a"
    assert APPEND == "append"


def test_query_for_keeps_baseline_and_appends_terms() -> None:
    gold = next(item for item in load_gold_suite(GOLD_DIR) if item.id == "confidentiality")
    assert query_for(gold, BASELINE) == gold.query
    expanded = query_for(gold, APPEND)
    assert gold.query in expanded
    assert "tystnadsplikt" in expanded


def test_expansion_stays_optional_and_does_not_replace_c8() -> None:
    assert EXPANSION_POLICY["default_retriever_unchanged"] is True
    assert EXPANSION_POLICY["router_unsolved"] is True
    assert EXPANSION_POLICY["jaccard_routing"] == "rejected"
    assert EXPANSION_POLICY["do_not_tune_jaccard_on_existing_golds"] is True
    assert EXPANSION_POLICY["does_not_replace_c8"] is True
    frozen = load_experimental_append_baseline()
    assert frozen["id"] == "phase2-coverage-v3-append-confidentiality"
    assert frozen["does_not_replace_c8"] is True
    assert frozen["does_not_replace_coverage_v3"] is True
    assert frozen["headline"]["first_complete_budget"] == 2
    assert frozen["headline"]["classified"] == 165
    assert frozen["headline"]["cumulative_jev_calls"] == 131
    assert frozen["headline"]["leftover_at_b1"] == [
        "Avtal_06_Sekretessavtal_ensidigt_NDA.docx"
    ]


def test_default_coverage_skips_held_out_golds() -> None:
    seen = _golds(None, GOLD_DIR)
    assert {gold.id for gold in seen} == {
        "auto-renewal",
        "notice-period",
        "liability-cap",
        "confidentiality",
        "liability-secrecy-carveout",
    }
    all_golds = _golds(None, GOLD_DIR, include_held_out=True)
    assert {gold.id for gold in all_golds} >= {"governing-law", "force-majeure"}


def test_held_out_terms_are_concept_variants_not_gold_snippets() -> None:
    expansions = load_expansions()
    for gold_id in ("governing-law", "force-majeure", "personal-data", "assignment"):
        gold = next(item for item in load_gold_suite(GOLD_DIR) if item.id == gold_id)
        terms = set(expansions[gold_id].terms)
        contains = {span.contains for span in gold.relevant_units}
        assert not terms & contains
        assert "svensk lag" not in terms
        assert not any("Svensk lag" in term for term in terms)
        assert not any("överlåta avtalet" in term for term in terms)


def test_compare_v3_reports_classified_and_recall_delta() -> None:
    baseline = {
        "golds": [
            {
                "gold_id": "confidentiality",
                "query": "q",
                "recall_at_50": 0.46,
                "budgets": [
                    {
                        "budget": 5,
                        "classified": 354,
                        "jev_calls": 115,
                        "document_recall": 1.0,
                        "jev_yes_document_recall": 1.0,
                        "budget_exhausted_documents": 56,
                    }
                ],
            }
        ]
    }
    treatment = {
        "golds": [
            {
                "gold_id": "confidentiality",
                "query_used": "q sekretess",
                "recall_at_50": 0.85,
                "budgets": [
                    {
                        "budget": 5,
                        "classified": 200,
                        "jev_calls": 40,
                        "document_recall": 1.0,
                        "jev_yes_document_recall": 1.0,
                        "budget_exhausted_documents": 40,
                    }
                ],
            }
        ]
    }
    compared = compare_v3_golds(baseline, treatment, gold_id="confidentiality", budgets=(5,))
    assert compared["budgets"][0]["delta"]["classified"] == -154
    assert compared["first_complete"]["treatment"]["classified"] == 200
