from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.coverage.leftover_discovery import discovery_documents
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_two_stage_retrieval_baseline,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.retrieval.two_stage import (
    ALLOCATIONS,
    TOTAL_BUDGET,
    UNLOCKS,
    diagnose_document,
    freeze_two_stage_retrieval,
    identify_documents,
    identification_ranks,
    run_two_stage_retrieval,
    score_candidates,
    two_stage_hits,
)


def _hit(path: str, key: str, rank: int, score: float | None = None) -> SearchHit:
    return SearchHit(rank, key, 1.0 / rank if score is None else score, rank, path, path, key)


def _unit(path: str, key: str) -> StoredUnit:
    return StoredUnit(1, key, path, path, key, None, None)


def test_quality_reference_stays_twenty_four() -> None:
    assert QUALITY_REFERENCE["true_support"] == 24
    assert UNLOCKS == ("avtal_135.docx", "avtal_159.docx", "avtal_168.docx")
    assert TOTAL_BUDGET == 50
    assert ALLOCATIONS == ((50, 1), (25, 2), (10, 5), (5, 10))
    assert RETRIEVAL_CONCLUSIONS["latest_quality_reference"] == "24/53"
    assert RETRIEVAL_CONCLUSIONS["two_stage_applied_to_v3"] is False
    assert RETRIEVAL_CONCLUSIONS["structure_guided_local_not_started"] is True


def test_identification_is_first_unique_documents() -> None:
    ranked = [
        _hit("avtal_155.docx", "a", 1),
        _hit("avtal_155.docx", "b", 2),
        _hit("avtal_111.docx", "c", 3),
        _hit("avtal_135.docx", "d", 4),
    ]
    assert identify_documents(ranked, 2) == ["avtal_155.docx", "avtal_111.docx"]
    assert identification_ranks(ranked)["avtal_135.docx"] == 3


def test_local_order_matches_global_filter() -> None:
    path = "avtal_155.docx"
    ranked = [
        _hit(path, "noise-1", 16, 0.9),
        _hit("avtal_002.docx", "other", 17, 0.8),
        _hit(path, "gold", 728, 0.1),
    ]
    row = diagnose_document(
        path,
        ranked=ranked,
        gold_keys=["gold"],
        units=[_unit(path, "noise-1"), _unit(path, "gold")],
    )
    assert row["first_document_rank"] == 16
    assert row["first_relevant_passage_rank"] == 728
    assert row["local_passage_rank"] == 2
    assert row["document_identification_rank"] == 1
    assert row["min_two_stage_budget"] == 2
    assert row["same_intra_document_order"] is True


def test_two_stage_keeps_total_budget_and_not_all_documents() -> None:
    ranked = []
    rank = 1
    for index in range(1, 6):
        path = f"avtal_{index:03d}.docx"
        ranked.append(_hit(path, f"u{index}a", rank))
        rank += 1
        ranked.append(_hit(path, f"u{index}b", rank))
        rank += 1
    for index in range(6, 12):
        ranked.append(_hit(f"avtal_{index:03d}.docx", f"u{index}", rank))
        rank += 1
    hits = two_stage_hits(ranked, 5, 2)
    assert len(hits) == 10
    assert {hit.relative_path for hit in hits} == {f"avtal_{index:03d}.docx" for index in range(1, 6)}


def test_two_stage_can_lift_a_late_passage_once_the_document_is_selected() -> None:
    leftover = ["avtal_155.docx", "avtal_135.docx"]
    gold_keys = {"avtal_155.docx": ["gold"], "avtal_135.docx": ["late"]}
    ranked = [_hit("avtal_155.docx", "noise", 1)]
    ranked.extend(_hit(f"avtal_{index:03d}.docx", f"x{index}", index - 15) for index in range(17, 66))
    ranked.append(_hit("avtal_155.docx", "gold", 51))
    ranked.append(_hit("avtal_135.docx", "late", 52))
    global_score = score_candidates(ranked[:50], leftover=leftover, gold_keys=gold_keys)
    local = score_candidates(
        two_stage_hits(ranked, 2, 2), leftover=leftover, gold_keys=gold_keys
    )
    assert "avtal_155.docx" in global_score["leftover_documents"]
    assert "avtal_155.docx" not in global_score["leftover_passages"]
    assert local["leftover_passages"] == ["avtal_155.docx"]
    assert local["unique_documents"] == 2
    assert local["candidates"] == 3


def test_injected_run_flags() -> None:
    payload = run_two_stage_retrieval(
        units=[],
        ranked=[_hit("avtal_002.docx", "other", 1)],
    )
    assert payload["no_new_jev"] is True
    assert payload["no_new_controller"] is True
    assert payload["does_not_change_proof"] is True
    assert payload["does_not_repeat_coverage_budget"] is True
    assert payload["structure_guided_local_not_started"] is True
    assert payload["improvement_is_budget_allocation"] is True
    assert payload["total_budget"] == 50
    assert set(payload["rows"]) == set(discovery_documents())
    assert freeze_two_stage_retrieval(payload)["does_not_repeat_coverage_budget"] is True


def test_two_stage_baseline() -> None:
    frozen = load_two_stage_retrieval_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["no_new_jev"] is True
    assert frozen["no_new_controller"] is True
    assert frozen["does_not_change_proof"] is True
    assert frozen["improvement_is_budget_allocation"] is True
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["total_budget"] == 50
    strategies = frozen["headline"]["strategies"]
    assert strategies["global_top_50"]["candidates"] == 50
    assert strategies["two_stage_50x1"]["candidates"] == 50
    assert strategies["two_stage_10x5"]["examines_all_documents"] is False
    assert strategies["two_stage_10x5"]["leftover_documents"] == []
    assert strategies["global_top_50"]["leftover_passages"] == [
        "avtal_121.docx",
        "avtal_127.docx",
    ]
    rows = frozen["headline"]["rows"]
    assert rows["avtal_155.docx"]["local_passage_rank"] == 10
    assert rows["avtal_155.docx"]["first_relevant_passage_rank"] == 728
    assert rows["avtal_135.docx"]["document_identification_rank"] == 88
    assert rows["avtal_159.docx"]["document_identification_rank"] == 51
    assert rows["avtal_168.docx"]["document_identification_rank"] == 72
    assert RETRIEVAL_CONCLUSIONS["two_stage_is_budget_allocation_if_same_scores"] is True
