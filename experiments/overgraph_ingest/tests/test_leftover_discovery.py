from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE, summarize
from overgraph_ingest.coverage.leftover_discovery import (
    BUDGET,
    BUDGET_EXHAUSTED,
    GLOBAL_K,
    NAVIGATION_MISS,
    NEVER_SEEDED,
    WRONG_PASSAGE,
    classify_cause,
    diagnose_row,
    discovery_documents,
    freeze_discovery_diagnosis,
    load_b5,
    run_discovery_diagnosis,
    short_id,
    summarize_rows,
)
from overgraph_ingest.coverage.state import NEEDS_ANALYSIS
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_discovery_diagnosis_baseline,
)
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


def _hit(path: str, key: str, rank: int) -> SearchHit:
    return SearchHit(rank, key, 1.0 / rank, rank, path, path, key)


def _unit(path: str, key: str, text: str) -> StoredUnit:
    return StoredUnit(1, key, path, path, text, None, None)


def test_quality_reference_stays_twenty_four() -> None:
    assert QUALITY_REFERENCE["true_support"] == 24
    assert QUALITY_REFERENCE["leftover_genuine"] == 29
    assert discovery_documents() == summarize()["tracks"]["discovery"]["documents"]
    assert len(discovery_documents()) == 14
    assert RETRIEVAL_CONCLUSIONS["latest_quality_reference"] == "24/53"
    assert RETRIEVAL_CONCLUSIONS["discovery_diagnosis_does_not_change_retrieval"] is True


def test_short_id_collapses_full_blind_paths() -> None:
    assert short_id("avtal_111.docx") == "avtal_111.docx"
    assert short_id("Avtal_135_Tystnadsplikt.docx") == "avtal_135.docx"


def test_classify_cause_splits_ranking_from_budget() -> None:
    assert classify_cause(
        first_document_rank=67,
        gold_passage_seeded=False,
        coverage_status=NEEDS_ANALYSIS,
    ) == NEVER_SEEDED
    assert classify_cause(
        first_document_rank=12,
        gold_passage_seeded=False,
        coverage_status=BUDGET_EXHAUSTED,
    ) == WRONG_PASSAGE
    assert classify_cause(
        first_document_rank=12,
        gold_passage_seeded=True,
        coverage_status=BUDGET_EXHAUSTED,
    ) == BUDGET_EXHAUSTED
    assert classify_cause(
        first_document_rank=12,
        gold_passage_seeded=True,
        coverage_status=NEEDS_ANALYSIS,
    ) == NAVIGATION_MISS


def test_wrong_passage_is_per_document_seed_cap() -> None:
    path = "avtal_114.docx"
    ranked = [_hit(path, f"noise-{index}", index) for index in range(1, 6)]
    ranked.append(_hit(path, "gold", 40))
    ranked.append(_hit("avtal_002.docx", "other", 41))
    row = diagnose_row(
        path,
        ranked=ranked,
        units=[_unit(path, "gold", "Detsamma gäller tystnadsplikt")]
        + [_unit(path, f"noise-{index}", "annat") for index in range(1, 6)],
        gold_keys=["gold"],
        coverage_status=BUDGET_EXHAUSTED,
        would_admit=False,
    )
    assert row["first_document_rank"] == 1
    assert row["first_relevant_passage_rank"] == 40
    assert row["candidates_in_global_k"] == 6
    assert row["gold_passage_seeded"] is False
    assert row["cause"] == WRONG_PASSAGE
    assert row["document_text_units"] == 6


def test_never_seeded_is_outside_global_k() -> None:
    path = "avtal_111.docx"
    ranked = [_hit("avtal_002.docx", "other", 1), _hit(path, "gold", 67)]
    row = diagnose_row(
        path,
        ranked=ranked,
        units=[_unit(path, "gold", "gäller inte")],
        gold_keys=["gold"],
        coverage_status=NEEDS_ANALYSIS,
        would_admit=False,
    )
    assert row["first_document_rank"] == 67
    assert row["seeded"] is False
    assert row["cause"] == NEVER_SEEDED
    assert row["gold_passage_beyond_global_k"] is True


def test_summary_keeps_three_unlocks() -> None:
    rows = [
        {
            "relative_path": "avtal_135.docx",
            "cause": NEVER_SEEDED,
            "coverage_status": NEEDS_ANALYSIS,
            "would_admit_if_found": True,
        },
        {
            "relative_path": "avtal_114.docx",
            "cause": WRONG_PASSAGE,
            "coverage_status": BUDGET_EXHAUSTED,
            "would_admit_if_found": False,
        },
        {
            "relative_path": "avtal_159.docx",
            "cause": NEVER_SEEDED,
            "coverage_status": NEEDS_ANALYSIS,
            "would_admit_if_found": True,
        },
        {
            "relative_path": "avtal_168.docx",
            "cause": BUDGET_EXHAUSTED,
            "coverage_status": BUDGET_EXHAUSTED,
            "would_admit_if_found": True,
        },
    ]
    summary = summarize_rows(rows)
    assert summary["causes"][NEVER_SEEDED] == 2
    assert summary["unlocks_if_examined_with_current_abilities"] == [
        "avtal_135.docx",
        "avtal_159.docx",
        "avtal_168.docx",
    ]
    assert summary["does_not_choose_next_action"] is True
    assert summary["quality_reference"]["true_support"] == 24


def test_injected_run_does_not_call_ranking() -> None:
    payload = run_discovery_diagnosis(
        units=[],
        ranked=[_hit("avtal_002.docx", "other", 1)],
    )
    assert payload["no_new_jev"] is True
    assert payload["no_new_controller"] is True
    assert payload["does_not_change_retrieval"] is True
    assert payload["applied_to_v3"] is False
    assert payload["ranking_computed"] is True
    assert payload["global_k"] == GLOBAL_K
    assert payload["budget"] == BUDGET
    assert set(payload["rows"]) == set(discovery_documents())
    assert payload["rows"]["avtal_135.docx"]["would_admit_if_found"] is True
    assert payload["rows"]["avtal_111.docx"]["would_admit_if_found"] is False
    assert freeze_discovery_diagnosis(payload)["does_not_add_omfattar_inte"] is True


def test_live_b5_matches_leftover_twenty_nine() -> None:
    b5 = load_b5()
    if not b5["source"]:
        return
    assert set(b5["unresolved_relevant"]) == set(discovery_documents())
    assert len(b5["budget_exhausted_relevant"]) == 8
    assert set(b5["budget_exhausted_relevant"]).issubset(discovery_documents())


def test_discovery_baseline() -> None:
    frozen = load_discovery_diagnosis_baseline()
    assert frozen["applied_to_v3"] is False
    assert frozen["no_new_jev"] is True
    assert frozen["no_new_controller"] is True
    assert frozen["does_not_change_retrieval"] is True
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["summary"]["documents"] == 14
    assert frozen["headline"]["ranking_computed"] is True
    assert frozen["headline"]["summary"]["causes"]["never_seeded"] == 7
    assert frozen["headline"]["summary"]["causes"]["wrong_passage_dominates"] == 5
    assert frozen["headline"]["summary"]["gold_passage_in_seed"] == [
        "avtal_121.docx",
        "avtal_127.docx",
    ]
    assert frozen["headline"]["summary"]["unlocks_if_examined_with_current_abilities"] == [
        "avtal_135.docx",
        "avtal_159.docx",
        "avtal_168.docx",
    ]
    assert RETRIEVAL_CONCLUSIONS["discovery_diagnosis_applied_to_v3"] is False
