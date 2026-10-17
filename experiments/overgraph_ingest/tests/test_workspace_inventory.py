from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE, summarize
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_workspace_inventory_baseline,
)
from overgraph_ingest.retrieval.two_stage import TWO_STAGE_ID, UNLOCKS
from overgraph_ingest.retrieval.workspace_inventory import (
    EXAMPLES,
    FUTURE_NOT_STARTED,
    REJECTED,
    TASKS,
    freeze_workspace_inventory,
    inventory_payload,
)


def test_two_limits_stay_independent() -> None:
    leftover = summarize()
    assert leftover["unexamined"] == 14
    assert leftover["examined"] == 15
    assert QUALITY_REFERENCE["true_support"] == 24
    assert leftover["unlocks_if_examined_with_current_abilities"] == list(UNLOCKS)
    assert TASKS["current_score"] == "same_passage_score_for_both"
    assert EXAMPLES["avtal_155.docx"]["constraint"] == "local_passage"
    assert EXAMPLES["avtal_135.docx"]["constraint"] == "document_identification"
    assert REJECTED["another_two_stage_experiment"] is True
    assert REJECTED["new_document_ranking_on_the_same_100"] is True
    assert "ingest_property_extraction" in FUTURE_NOT_STARTED


def test_workspace_inventory_baseline() -> None:
    frozen = load_workspace_inventory_baseline()
    assert frozen["verdict"] == "rejected_as_completeness"
    assert frozen["two_stage_is_negative"] is True
    assert frozen["does_not_start_another_two_stage"] is True
    assert frozen["does_not_build_document_ranking"] is True
    assert frozen["does_not_tune_ranking_on_same_100"] is True
    assert frozen["does_not_start_ingest_enrichment"] is True
    assert frozen["top50_is_not_completeness"] is True
    assert frozen["headline"]["quality_reference"]["true_support"] == 24
    assert frozen["headline"]["limits"]["discovery"]["unexamined"] == 14
    assert frozen["headline"]["limits"]["proof_evaluation"]["examined_undecided"] == 15
    assert frozen["headline"]["does_not_require_jev_on_every_document"] is True
    assert RETRIEVAL_CONCLUSIONS["latest_quality_reference"] == "24/53"
    assert RETRIEVAL_CONCLUSIONS["two_stage_rejected_for_workspace_inventory"] is True
    assert RETRIEVAL_CONCLUSIONS["top50_is_not_workspace_completeness"] is True
    assert RETRIEVAL_CONCLUSIONS["ingest_property_extraction_not_started"] is True
    payload = inventory_payload()
    assert payload["two_stage_measurement"] == TWO_STAGE_ID
    assert payload["stage1_marks_needed_for_all_fourteen"] == 100
    assert freeze_workspace_inventory(payload)["id"] == "phase2-workspace-inventory-v1"
