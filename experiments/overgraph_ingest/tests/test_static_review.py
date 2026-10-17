from overgraph_ingest.coverage.cache import _judgment_rows
from overgraph_ingest.coverage.evidence_run import _positive
from overgraph_ingest.coverage.state import EVIDENCE_FOUND, DocumentState, UnitRecord, resolve_status
from overgraph_ingest.coverage.static_review import (
    ACCEPTED,
    freeze_static_review_baseline,
    review_payload,
)
from overgraph_ingest.coverage.evidence import admit_evidence_found
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_static_review_baseline,
)
from overgraph_ingest.retrieval.search import _score
from overgraph_ingest.retrieval.index import StoredUnit


def test_v3_composite_yes_plus_hop_is_not_admit() -> None:
    doc = DocumentState(
        "avtal_x.docx",
        2,
        [
            UnitRecord("a", "YES", "hyp", text="taket gäller inte för annat"),
            UnitRecord("b", "NO", "hop", hop="hop:PREVIOUS", text="Sekretess"),
        ],
        hop_attempted=True,
    )
    assert resolve_status(doc, proof_kind="COMPOSITE") == EVIDENCE_FOUND
    assert ACCEPTED["v3_composite_yes_plus_hop_is_not_verified_relation"] is True
    assert ACCEPTED["admit_evidence_found_not_called_by_resolve_status"] is True
    assert "admit_evidence_found" not in resolve_status.__code__.co_names
    assert admit_evidence_found.__module__ == "overgraph_ingest.coverage.evidence"


def test_evidence_run_can_substitute_gold_snippet() -> None:
    snippet = "gäller inte vid brott mot sekretess"
    judged = _positive(
        "avtal_x.docx",
        snippet,
        [{"relative_path": "avtal_x.docx", "predicted": "YES", "text": "annat tak", "key": "u1"}],
    )
    assert judged["spans"]
    assert "gäller inte" in judged["spans"][0]["text"]
    assert "annat tak" not in judged["spans"][0]["text"]
    assert ACCEPTED["evidence_run_can_substitute_gold_snippet"] is True


def test_c8_cache_falls_back_to_first_run() -> None:
    rows = _judgment_rows(
        {
            "runs": [
                {
                    "variant": "other",
                    "concurrency": 2,
                    "batch_size": 4,
                    "wall_judgments": [{"key": "u1", "predicted": "YES"}],
                }
            ]
        }
    )
    assert rows == [{"key": "u1", "predicted": "YES"}]
    assert ACCEPTED["c8_cache_can_fall_back_to_first_run"] is True


def test_exhaustive_hybrid_adds_scores() -> None:
    unit = StoredUnit(
        node_id=1,
        key="u1",
        document_id="d",
        relative_path="a.docx",
        text="x",
        dense=[1.0, 0.0],
        sparse=[(0, 1.0)],
    )
    assert _score(unit, "hybrid", [1.0, 0.0], [(0, 1.0)]) == _score(
        unit, "dense", [1.0, 0.0], None
    ) + _score(unit, "sparse", None, [(0, 1.0)])
    assert ACCEPTED["exhaustive_hybrid_score_is_not_rrf"] is True


def test_static_review_baseline() -> None:
    frozen = load_static_review_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["does_not_start_next_ability"] is True
    assert frozen["headline"]["accepted"]["nineteen_of_fifty_three_is_not_v3_verification"] is True
    assert RETRIEVAL_CONCLUSIONS["nineteen_of_fifty_three_is_not_v3_verification"] is True
    payload = review_payload()
    assert payload["quality_reference"]["true_support"] == 19
    assert freeze_static_review_baseline(payload)["id"] == "phase2-static-review-v1"
