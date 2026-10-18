from overgraph_ingest.cerebras.escalation import freeze_second_opinion_rejected
from overgraph_ingest.cerebras.modes import freeze_cerebras_modes
from overgraph_ingest.cerebras.prompt import MATCH, NO_MATCH, UNCERTAIN
from overgraph_ingest.cerebras.second_opinion import (
    compare_pairs,
    freeze_cerebras_second_opinion,
    pair_effect,
    role,
)
from overgraph_ingest.phase_close import freeze_phase_close
from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
YES = "YES"
from overgraph_ingest.retrieval.conclusions import (
    RETRIEVAL_CONCLUSIONS,
    load_cerebras_escalation_baseline,
    load_cerebras_modes_baseline,
    load_cerebras_second_opinion_baseline,
    load_phase_close_baseline,
)


def test_pair_effect_counts_correction_regression_and_same_error() -> None:
    assert pair_effect("false_positive", "true_negative") == "corrected"
    assert pair_effect("false_negative", "true_positive") == "corrected"
    assert pair_effect("true_positive", "false_negative") == "worsened"
    assert pair_effect("true_negative", "false_positive") == "worsened"
    assert pair_effect("false_positive", "false_positive") == "same_error"
    assert pair_effect("false_negative", "false_positive") == "shared_error"
    assert pair_effect("uncertain", "true_positive") == "uncertain_resolved_correct"
    assert pair_effect("uncertain", "false_positive") == "uncertain_resolved_wrong"


def test_role_does_not_treat_uncertain_as_error() -> None:
    assert role(label=UNCERTAIN, relevant=True) == "uncertain"
    assert role(label=YES, relevant=True) == "true_positive"
    assert role(label=MATCH, relevant=False) == "false_positive"
    assert role(label=NO_MATCH, relevant=True) == "false_negative"


def test_compare_pairs_on_overlap_only() -> None:
    compared = compare_pairs(
        jev={
            "gold": YES,
            "false": YES,
            "miss": "NO",
            "ok": "NO",
            "unsure": UNCERTAIN,
            "jev_only": YES,
        },
        cerebras={
            "gold": MATCH,
            "false": NO_MATCH,
            "miss": MATCH,
            "ok": MATCH,
            "unsure": MATCH,
            "cerebras_only": MATCH,
        },
        corpus_keys={"gold", "miss", "unsure"},
    )
    assert compared["overlap"] == 5
    assert compared["jev_only"] == ["jev_only"]
    assert compared["cerebras_only"] == ["cerebras_only"]
    assert compared["corrected"] == 2
    assert compared["worsened"] == 1
    assert compared["same_error"] == 0
    assert compared["uncertain_resolved_correct"] == 1
    assert compared["jev_errors"] == 2
    assert compared["uncertain_review"]["reviewed"] == 1
    assert compared["uncertain_review"]["resolved_correct"] == 1


def test_modes_keep_1x50_as_fast_baseline() -> None:
    frozen = freeze_cerebras_modes()
    assert frozen["verdict"] == "keep_1x50_fast_baseline"
    assert frozen["fast_mode"] == "phase2-cerebras-output-v1"
    assert frozen["scale_mode"] == "phase2-cerebras-split50-v1"
    assert frozen["no_automatic_k_routing"] is True
    assert frozen["k200_not_started"] is True
    assert frozen["next_isolated_experiment"] == "second_opinion"
    assert frozen["headline"]["fast"]["true_matches"] == 72
    assert frozen["headline"]["scale"]["true_matches"] == 79
    assert frozen["headline"]["scale"]["lost_from_k50_true_matches"] == 0
    assert RETRIEVAL_CONCLUSIONS["best_fast_naive_rerank"] == "phase2-cerebras-output-v1"
    assert RETRIEVAL_CONCLUSIONS["no_automatic_k_routing"] is True


def test_cerebras_modes_baseline() -> None:
    frozen = load_cerebras_modes_baseline()
    assert frozen["verdict"] == "keep_1x50_fast_baseline"
    assert frozen["no_automatic_k_routing"] is True
    assert frozen["k200_not_started"] is True
    assert frozen["headline"]["fast"]["true_matches"] == 72
    assert frozen["headline"]["scale"]["true_matches"] == 79


def test_cerebras_second_opinion_baseline() -> None:
    frozen = load_cerebras_second_opinion_baseline()
    assert frozen["no_router"] is True
    assert frozen["no_new_jev"] is True
    assert frozen["k200_not_started"] is True
    assert frozen["headline"]["summary"]["total_overlap"] == 233
    assert frozen["headline"]["summary"]["total_corrected"] == 8
    assert frozen["headline"]["summary"]["total_worsened"] == 7
    assert frozen["headline"]["summary"]["total_same_error"] == 19
    assert frozen["headline"]["summary"]["total_uncertain_resolved_wrong"] == 0
    golds = {row["gold_id"]: row for row in frozen["headline"]["golds"]}
    assert golds["auto-renewal"]["corrected"] == 2
    assert golds["notice-period"]["worsened"] == 3
    assert golds["confidentiality"]["same_error"] == 10
    assert RETRIEVAL_CONCLUSIONS["second_opinion_is_replay"] is True
    assert RETRIEVAL_CONCLUSIONS["second_opinion_router_not_started"] is True
    assert RETRIEVAL_CONCLUSIONS["cerebras_second_opinion"] == (
        "rejected_for_general_escalation"
    )
    assert RETRIEVAL_CONCLUSIONS["do_not_build_model_router"] is True


def test_second_opinion_is_rejected_for_general_escalation() -> None:
    frozen = freeze_second_opinion_rejected()
    assert frozen["verdict"] == "rejected_for_general_escalation"
    assert frozen["do_not_build_model_router"] is True
    assert frozen["disagreement_is_not_uncertainty"] is True
    assert frozen["uncertain_does_not_steer_escalation"] is True
    assert frozen["classify_reference"] == "phase2-jev-classify-c8"
    assert frozen["headline"]["summary"]["net"] == 1
    assert frozen["headline"]["summary"]["same_error"] == 19


def test_phase_close_does_not_start_socialism() -> None:
    frozen = freeze_phase_close()
    assert frozen["does_not_start_socialism_integration"] is True
    assert frozen["does_not_build_model_router"] is True
    assert frozen["does_not_start_next_ability"] is True
    names = {row["ability"] for row in frozen["headline"]["consider_for_socialism"]}
    assert names == {"docx_ingest", "hybrid_search", "jev_c8_classify"}
    rejected = {row["ability"] for row in frozen["headline"]["rejected"]}
    assert "second_opinion_escalation" in rejected
    assert "k200" in frozen["headline"]["do_not_start"]


def test_escalation_and_phase_close_baselines() -> None:
    rejected = load_cerebras_escalation_baseline()
    assert rejected["verdict"] == "rejected_for_general_escalation"
    assert rejected["headline"]["summary"]["net"] == 1
    closed = load_phase_close_baseline()
    assert closed["does_not_start_socialism_integration"] is True
    assert RETRIEVAL_CONCLUSIONS["second_opinion_track_closed"] is True
    assert RETRIEVAL_CONCLUSIONS["phase_close_does_not_start_socialism"] is True


def test_second_opinion_freeze_builds_no_router() -> None:
    frozen = freeze_cerebras_second_opinion(
        {
            "quality_reference": QUALITY_REFERENCE,
            "summary": {},
            "golds": [],
        }
    )
    assert frozen["no_router"] is True
    assert frozen["no_new_jev"] is True
    assert frozen["no_new_cerebras"] is True
    assert frozen["k200_not_started"] is True
    assert frozen["does_not_replace_c8"] is True
