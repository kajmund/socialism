import pytest

from overgraph_ingest.jev.baseline import ARCHITECTURE, load_official_classify_baseline
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_bge_m3_rejection,
    load_jaccard_rejection,
    load_overgraph_search_baseline,
)
from overgraph_ingest.retrieval.decide import (
    DISAGREE_MIN_JACCARD,
    JACCARD_ROUTING,
    dense_sparse_disagree,
    should_expand,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.profile import profile_python
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.retrieval.stages import EVIDENCE_LAYERS, PIPELINE_STAGES


def test_pipeline_keeps_representation_separate() -> None:
    assert PIPELINE_STAGES == (
        "question",
        "representation",
        "retrieval",
        "classify",
        "coverage",
    )
    assert EVIDENCE_LAYERS == ("retrieval", "proof_evaluation", "navigation")
    assert "classify" not in EVIDENCE_LAYERS


def test_python_profile_times_score_and_rank_separately() -> None:
    units = [
        StoredUnit(1, "a", "d", "a.docx", "sekretess", [1.0, 0.0], [(1, 1.0)]),
        StoredUnit(2, "b", "d", "b.docx", "annat", [0.0, 1.0], [(2, 1.0)]),
    ]
    payload = profile_python(units, [1.0, 0.0], [(1, 1.0)], repeats=1)
    assert payload["python_dense_score"]["result_count"] == 2
    assert payload["python_dense_rank"]["result_count"] == 2
    assert payload["python_sparse_rank"]["result_count"] == 2
    sequential = payload["python_dense_then_sparse"]["mean_seconds"]
    assert sequential >= payload["python_dense_rank"]["mean_seconds"]
    assert sequential >= payload["python_sparse_rank"]["mean_seconds"]


def test_overgraph_search_baseline_is_frozen_and_not_c8() -> None:
    frozen = load_overgraph_search_baseline()
    official = load_official_classify_baseline()
    assert frozen["id"] == "phase2-overgraph-hybrid-search"
    assert frozen["do_not_optimize_engine"] is True
    assert frozen["does_not_replace_c8"] is True
    assert frozen["id"] != official["id"]
    assert frozen["headline"]["engine_hybrid_seconds"] == pytest.approx(0.011648683436214924)
    assert frozen["headline"]["normal_retrieval_seconds"] == pytest.approx(0.2295)
    assert RETRIEVAL_CONCLUSIONS["engine_search"] == "do_not_optimize"
    assert ARCHITECTURE["prompt_batching"] == "rejected_for_classify"


def test_jaccard_routing_is_rejected_like_prompt_batching() -> None:
    frozen = load_jaccard_rejection()
    assert frozen["id"] == "phase2-jaccard-expansion-routing-rejected"
    assert frozen["verdict"] == "rejected"
    assert frozen["do_not_tune_threshold_on_existing_golds"] is True
    assert frozen["expanded_every_gold"] is True
    assert frozen["notice_period_regressed"] is True
    assert JACCARD_ROUTING == "rejected"
    assert RETRIEVAL_CONCLUSIONS["jaccard_expansion_routing"] == "rejected"
    assert DISAGREE_MIN_JACCARD == 0.25


def test_bge_m3_is_rejected_and_openai_tfidf_stays_default() -> None:
    frozen = load_bge_m3_rejection()
    official = load_official_classify_baseline()
    assert frozen["id"] == "phase2-bge-m3-rejected"
    assert frozen["verdict"] == "rejected"
    assert frozen["do_not_deploy"] is True
    assert frozen["default_retriever"] == "openai-tfidf"
    assert frozen["id"] != official["id"]
    assert frozen["hybrid_recall_at_50"]["liability-cap"]["openai-tfidf"] == pytest.approx(
        0.8529411764705882
    )
    assert frozen["hybrid_recall_at_50"]["liability-cap"]["bge-m3"] == pytest.approx(
        0.6176470588235294
    )
    assert RETRIEVAL_CONCLUSIONS["bge_m3"] == "rejected"
    assert RETRIEVAL_CONCLUSIONS["default_retriever"] == "openai-tfidf"


def test_disagree_rule_is_fixed_and_model_free() -> None:
    assert DISAGREE_MIN_JACCARD == 0.25
    overlap = [
        SearchHit(1, "a", 1.0, 1, "d", "a.docx", "x"),
        SearchHit(2, "b", 0.5, 2, "d", "b.docx", "y"),
    ]
    disjoint = [
        SearchHit(3, "c", 1.0, 1, "d", "c.docx", "z"),
        SearchHit(4, "d", 0.5, 2, "d", "d.docx", "w"),
    ]
    assert dense_sparse_disagree(overlap, overlap) is False
    assert dense_sparse_disagree(overlap, disjoint) is True
    assert should_expand("never", overlap, disjoint) is False
    assert should_expand("always", overlap, overlap) is True
    assert should_expand("dense_sparse_disagree", overlap, disjoint) is True
