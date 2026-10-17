"""Frozen retrieval conclusions. Does not replace official C@8."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEARCH_BASELINE_ID = "phase2-overgraph-hybrid-search"
SEARCH_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{SEARCH_BASELINE_ID}.json"
)
JACCARD_REJECTION_ID = "phase2-jaccard-expansion-routing-rejected"
JACCARD_REJECTION_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{JACCARD_REJECTION_ID}.json"
)
BGE_M3_REJECTION_ID = "phase2-bge-m3-rejected"
BGE_M3_REJECTION_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{BGE_M3_REJECTION_ID}.json"
)

RETRIEVAL_CONCLUSIONS = {
    "engine_search": "do_not_optimize",
    "jaccard_expansion_routing": "rejected",
    "do_not_tune_jaccard_on_existing_golds": True,
    "bge_m3": "rejected",
    "default_retriever": "openai-tfidf",
    "query_expansion": "optional_not_default",
    "completeness": "unsolved",
    "does_not_replace_c8": True,
    "do_not_optimize_first_yes": True,
    "evidence_contracts": {
        "document_existence": "first_verified_positive_may_answer",
        "workspace_inventory": "every_document_verified_or_unresolved",
    },
    "workspace_stop_rule": "not_chosen",
    "investigation_results": ("COMPLETE", "PARTIAL", "FAILED"),
    "partial_must_be_disclosed": True,
    "jev_yes_is_not_legal_evidence": True,
    "no_general_stop_budget": True,
    "problem_is_work_allocation": True,
    "work_kinds": ("discovery", "proof_completion"),
    "proof_gap_frozen": True,
    "proof_contract_applied_to_v3": False,
    "proof_relation_ready": False,
    "rule_b_rejected": True,
    "cooccurrence_is_not_a_relation": True,
    "relation_requires_source_span": True,
    "proof_link_applied_to_v3": False,
    "proof_link_live_zero_false": True,
    "composite_describes_proof_not_unit_count": True,
    "evidence_layers": ("retrieval", "proof_evaluation", "navigation"),
    "reward_sufficient_evidence_not_more_steps": True,
    "extra_classifications_are_mostly": "other_document_discovery",
    "link_detector_is_formulation_bound": True,
    "proof_jev_applied_to_classify": False,
    "proof_jev_zero_false_complete": False,
    "proof_jev_rejected_for_standalone": True,
    "proof_gate_applied_to_v3": False,
    "proof_gate_zero_false_complete": True,
    "proof_gate_coverage_zero_false": False,
    "proof_gate_blocked_true_positive": True,
    "document_structure_decides_referents": True,
    "unresolved_polarity_is_undecided": True,
    "evidence_found_has_no_span": True,
    "hop_always_is_not_proof": True,
    "jev_yes_is_not_proof": True,
    "evidence_found_requires_validated_proof": True,
    "evidence_proof_applied_to_v3": False,
    "evidence_proof_zero_false_complete": True,
    "span_validation_is_not_relation_validation": True,
    "quote_and_yes_is_not_proof": True,
    "proof_logic_applied_to_v3": False,
    "jev_proposes_predicate_not_supported": True,
    "proposed_is_not_evidence_found": True,
    "predicate_applied_to_v3": False,
    "do_not_loosen_verified_for_proposed": True,
    "more_hops_do_not_verify_proposed": True,
    "next_open_cost": "evidence_found_must_answer_dependencies",
    "blind_gold_is_synthetic": True,
    "seen_detectors_miss_blind_yes": True,
    "decision_traces_observed": True,
    "uncertain_is_not_false_complete": True,
    "gold_tests_prevailing_terms": True,
    "proof_requirements_applied_to_v3": False,
    "examined_support_is_not_exhaustive_absence": True,
    "unseen_amendment_is_not_proof_of_absence": True,
    "gold_map_v2_does_not_rewrite_history": True,
    "next_completion_replaces_yes_plus_hop": True,
    "failure_kinds_must_not_share_a_fix": (
        "wrong_decision_contract",
        "lacking_semantic_understanding",
        "gold_mapping_miss",
    ),
    "same_mapping_for_both_variants": "gold-map-v2",
    "decision_contract_applied_to_v3": False,
    "approved_chain_does_not_upgrade_investigation": True,
    "finding_clause_is_not_admission": True,
    "undecided_remains_searchable": True,
    "known_cases_are_regression_tests": True,
    "clause_resolve_applied_to_v3": False,
    "anaphor_list_applied_to_v3": False,
    "does_not_concatenate_units": True,
    "leftover_diagnosis_applied_to_v3": False,
    "latest_quality_reference": "24/53",
    "previous_quality_reference": "19/53",
    "leftover_diagnosis_does_not_start_next_ability": True,
    "ability_review_does_not_start_next_ability": True,
    "exception_paraphrase_is_not_one_construction": True,
    "citation_label_source_relation_already_holds": True,
    "predication_model_is_not_ready_for_paraphrase": True,
    "nineteen_of_fifty_three_is_not_v3_verification": True,
    "v3_composite_yes_plus_hop_is_not_verified_relation": True,
    "zero_false_approvals_is_frozen_set_not_population": True,
    "official_comparison_requires_named_c8": True,
    "quality_metric_must_disclose_gold_supply": True,
    "experimental_proof_rules_are_not_production": True,
    "future_proof_evaluation_not_decided": True,
    "citation_label_applied_to_v3": False,
    "does_not_change_relation_test": True,
    "leftover_29_does_not_start_next_ability": True,
    "discovery_diagnosis_applied_to_v3": False,
    "discovery_diagnosis_does_not_change_retrieval": True,
    "two_stage_applied_to_v3": False,
    "two_stage_is_budget_allocation_if_same_scores": True,
    "structure_guided_local_not_started": True,
    "two_stage_rejected_for_workspace_inventory": True,
    "top50_is_not_workspace_completeness": True,
    "do_not_start_another_two_stage": True,
    "do_not_build_document_ranking_yet": True,
    "do_not_tune_ranking_on_same_100": True,
    "ingest_property_extraction_not_started": True,
    "discovery_and_proof_are_independent_limits": True,
    "cerebras_rerank_applied_to_v3": False,
    "cerebras_rerank_is_formulation_presence": True,
    "cerebras_rerank_does_not_replace_c8": True,
    "cerebras_output_does_not_replace_rerank": True,
    "cerebras_qwen_does_not_replace_output": True,
    "cerebras_qwen_does_not_replace_c8": True,
    "cerebras_qwen_is_formulation_presence": True,
    "cerebras_qwen": "rejected_for_naive_rerank",
    "best_naive_rerank": "phase2-cerebras-output-v1",
    "cerebras_reasoning_off_supported": False,
    "best_naive_rerank_setting": "gpt-oss-120b-medium-minimal-json",
    "do_not_tune_reasoning_on_same_five": True,
    "low_is_not_quality_equivalent": True,
    "k200_not_started": True,
    "second_opinion_not_started": True,
    "cerebras_k100_medium_does_not_complete": True,
    "cerebras_k100_one_shot_quality_unmeasured": True,
    "cerebras_k100_does_not_prove_one_shot_impossible": True,
    "cerebras_k100_cap_raised_to_measure_json": True,
    "cerebras_split50_is_formulation_presence": True,
    "cerebras_split50_does_not_replace_k100": True,
    "cerebras_split50_completes": True,
    "best_fast_naive_rerank": "phase2-cerebras-output-v1",
    "naive_scale_mode": "phase2-cerebras-split50-v1",
    "no_automatic_k_routing": True,
    "second_opinion_router_not_started": True,
    "second_opinion_is_replay": True,
    "cerebras_second_opinion": "rejected_for_general_escalation",
    "do_not_build_model_router": True,
    "disagreement_is_not_uncertainty": True,
    "uncertain_does_not_steer_escalation": True,
    "jev_c8_remains_classify_reference": True,
    "second_opinion_track_closed": True,
    "phase_close_does_not_start_socialism": True,
    "tabular_review": "measured_v1",
    "tabular_review_does_not_replace_c8": True,
    "tabular_review_does_not_import_hop_always": True,
    "tabular_cell_accuracy_is_not_24_53": True,
    "tabular_second_run_100_not_started": True,
    "tabular_selection_is_diagnostic": True,
    "tabular_jev_requested_no_hops": True,
    "tabular_a_did_not_beat_b": True,
    "tabular_cerebras_did_not_beat_jev": True,
    "tabular_qwen": "measured_v1",
    "tabular_qwen_reasoning": "low",
    "tabular_qwen_same_100_cells": True,
    "tabular_qwen_no_new_retrieval": True,
    "tabular_qwen_does_not_replace_tabular_v1": True,
    "tabular_qwen_does_not_replace_c8": True,
    "tabular_qwen_did_not_beat_jev": True,
    "tabular_qwen_beat_cerebras": True,
    "tabular_qwen_navigation_not_changed": True,
    "tabular_quality_reference": "jev_b",
    "tabular_model_comparisons": "paused",
    "tabular_citation": "measured_v1",
    "tabular_citation_is_retrieval_not_selection": True,
    "tabular_citation_accuracy_is_not_source_choice": True,
    "tabular_next_is_document_local_retrieval": True,
    "tabular_confidentiality_is_the_gap": True,
    "do_not_test_more_tabular_models": True,
    "do_not_build_tabular_navigation": True,
    "tabular_k10": "measured_v1",
    "tabular_k10_did_not_beat_k5": True,
    "tabular_k10_recovered_confidentiality": True,
    "tabular_k10_added_false_answers": True,
    "tabular_default_k": 5,
    "tabular_default_k_unchanged": True,
    "do_not_widen_tabular_k": True,
    "tabular_k10_errors": "measured_v1",
    "tabular_b_classify_does_not_gate_answer": True,
    "tabular_answer_sees_all_examined": True,
    "tabular_k10_false_positives_are_new_tail": True,
    "do_not_build_tabular_controller": True,
    "do_not_change_jev_prompt": True,
    "do_not_start_new_embedding": True,
    "do_not_feed_classify_into_answer": True,
    "do_not_change_default_b": True,
    "tabular_direct_hypothesis": "A",
    "tabular_direct": "measured_v1",
    "tabular_direct_held_quality": True,
    "tabular_direct_saved_jev_calls": True,
    "tabular_direct_did_not_beat_b": True,
    "tabular_next_is_two_step_vs_direct": False,
    "tabular_performance_reference": "jev_d",
    "tabular_historical_two_step": "jev_b",
    "tabular_pipeline": "document_local_top5_answer_cell",
    "do_not_test_hypothesis_b": True,
    "do_not_promise_local_jev_latency": True,
    "tabular_next_is_right_five": True,
    "tabular_next_is_not_more_model_steps": True,
    "tabular_signals": "measured_v1",
    "tabular_dense_hit5_beat_hybrid": True,
    "tabular_sparse_did_not_beat_hybrid": True,
    "tabular_dense_recovered_confidentiality": True,
    "tabular_answer_cell_warranted_for_dense": True,
    "do_not_assume_recall_is_cell_quality": True,
    "do_not_change_default_hybrid": True,
    "tabular_next_is_dense_answer_cell": False,
    "tabular_dense": "measured_v1",
    "tabular_dense_did_not_beat_hybrid_d": True,
    "tabular_dense_recovered_confidentiality_cells": True,
    "tabular_dense_added_false_answers": True,
    "tabular_dense_errors": "measured_v1",
    "tabular_dense_false_positives_are_new_units": True,
    "tabular_threshold_hypothesis_not_measured": True,
    "do_not_change_prompt_from_dense_errors": True,
    "tabular_prompt_dev": "measured_v1",
    "tabular_prompt_dev_picked": "P0",
    "tabular_prompt_did_not_beat_p0": True,
    "tabular_prompt_did_not_fix_avtal_13": True,
    "do_not_treat_known_errors_as_quality_gold": True,
    "tabular_holdout_not_run": True,
    "tabular_prompt_en": "measured_v1",
    "tabular_prompt_en_did_not_beat_swedish": True,
    "tabular_prompt_en_added_false_answers": True,
    "default_question_language_unchanged": True,
    "tabular_status_v2": "measured_v1",
    "tabular_status_v2_nearby_is_uncertain": True,
    "tabular_status_v2_d_met_acceptance": True,
    "tabular_status_v2_experiment_winner": "P0_v2_D",
    "tabular_status_v2_repeats": "measured_v1",
    "tabular_status_v2_unused_hard_neg_are_in_distribution": True,
    "tabular_status_v2_holdout_exclusions_unseen": True,
    "tabular_status_v2_d_repeat_spread_zero": True,
    "tabular_status_v2_d_holdout_false_answered": True,
    "tabular_status_v2_d_did_not_generalize": True,
    "tabular_probability": "measured_v1",
    "tabular_probability_rejected": True,
    "tabular_probability_p2_implemented": False,
    "tabular_probability_score_type": "jev_choice_confidence",
    "tabular_probability_usable_separation": False,
    "tabular_probability_keep_explicit_uncertain": True,
    "tabular_probability_kept_for_diagnostics": True,
    "do_not_build_score_threshold": True,
    "tabular_parameter_tuning_plateau_on_100": True,
    "tabular_next_is_question_gold_alignment": True,
    "do_not_retune_gold_to_model": True,
    "tabular_question_gold": "diagnosed_v1",
    "tabular_user_gold": "measured_v1",
    "historical_cell_accuracy_is_not_user_quality": True,
    "user_question_is_the_contract": True,
    "do_not_overwrite_retrieval_gold": True,
    "tabular_e_beat_d_on_user_gold": True,
    "tabular_k_tied_e_on_user_gold": True,
    "tabular_default_remains_d": True,
    "tabular_e_is_next_candidate": True,
    "do_not_switch_default_on_diagnostic_20": True,
    "do_not_add_special_rules_for_nearby_errors": True,
    "do_not_keep_optimizing_diagnostic_20": True,
    "tabular_cell_may_have_multiple_answers": True,
    "tabular_holdout": "gold_before_models",
    "tabular_holdout_models_not_run": False,
    "tabular_holdout_run": "measured_v1",
    "tabular_holdout_e_full_success": 0.89,
    "tabular_holdout_d_full_success": 0.79,
    "tabular_holdout_e_positive_correct": 39,
    "tabular_holdout_d_positive_correct": 27,
    "tabular_holdout_e_silent_false": 6,
    "tabular_holdout_d_silent_false": 5,
    "tabular_holdout_k_did_not_beat_e": True,
    "tabular_holdout_do_not_pay_k10": True,
    "do_not_mix_structural_ingest_into_holdout": True,
    "tabular_enrich": "protocol_v1",
    "tabular_enrich_first_run": ("A", "B"),
    "tabular_enrich_run": "measured_v1",
    "tabular_enrich_b_did_not_beat_a_at_k5": True,
    "tabular_enrich_c_not_run": True,
    "tabular_enrich_jev_not_run": True,
    "tabular_enrich_hypothesis_2_not_built": True,
    "search_is_not_evidence": True,
    "do_not_tune_structure_to_known_misses": True,
    "do_not_run_c_automatically": True,
    "tabular_enrich_b_rejected": True,
    "tabular_original_embeddings_stay": True,
    "tabular_next_is_candidate_presentation": True,
    "tabular_present": "protocol_v1",
    "tabular_present_models_not_run": False,
    "tabular_present_run": "measured_v1",
    "tabular_present_did_not_reduce_silent_false": True,
    "tabular_present_lost_positive": 1,
    "tabular_present_changed_cells": 8,
    "do_not_add_more_metadata_fields": True,
    "do_not_run_reserved_holdout": True,
    "tabular_present_rejected": True,
    "tabular_present_kept": "text",
    "tabular_structure_to_jev_rejected": True,
    "tabular_micro_optimization_paused": True,
    "do_not_start_hypothesis_2_because_cheaper_failed": True,
    "next_quality_needs_new_capability": True,
    "do_not_compare_development_present_to_holdout": True,
    "tabular_e_is_strongest_measured_candidate": True,
    "tabular_multi_run": "measured_v1",
    "tabular_multi_found_more_gold": True,
    "tabular_multi_added_extras": True,
    "tabular_multi_did_not_win_without_extras": True,
    "do_not_start_product_from_multi_run": True,
    "doctype_classification": "measured_v1",
    "doctype_is_document_property": True,
    "doctype_does_not_change_text_units": True,
    "doctype_does_not_change_answer_cell": True,
    "doctype_does_not_change_retrieval": True,
    "doctype_no_production_integration": True,
    "doctype_principal_function_not_clauses": True,
    "doctype_models_not_run": False,
    "doctype_best_variant": "B",
    "doctype_a_accuracy": 0.81,
    "doctype_b_accuracy": 0.86,
    "doctype_c_accuracy": 0.84,
    "doctype_jev_adds_measurable_quality": True,
    "doctype_wider_context_improves": False,
    "doctype_text_units_unchanged": True,
    "doctype_filter_works": True,
    "document_tags": "measured_v1",
    "document_tags_does_not_change_text_units": True,
    "document_tags_does_not_change_answer_cell": True,
    "document_tags_does_not_change_retrieval": True,
    "document_tags_does_not_change_doctype_baseline": True,
    "document_tags_no_production_integration": True,
    "document_tags_reuses_frozen_doctype_b": True,
    "document_tags_does_not_rerun_doctype_jev": True,
    "document_tags_no_automatic_approval_threshold": True,
    "document_tags_confidence_is_not_legal_probability": True,
    "document_tags_prepared_knowledge_not_legal_proof": True,
    "document_tags_models_not_run": False,
    "document_tags_best_variant": "A",
    "document_tags_a_precision": 0.8648648648648649,
    "document_tags_a_recall": 0.9411764705882353,
    "document_tags_b_precision": 0.9142857142857143,
    "document_tags_b_recall": 0.9411764705882353,
    "document_tags_a_hits": 32,
    "document_tags_b_hits": 32,
    "document_tags_gold_n": 34,
    "document_tags_jev_adds_measurable_quality": False,
    "document_tags_text_units_unchanged": True,
    "document_tags_filter_works": True,
    "document_tags_type_correction_survives": True,
    "document_tags_rejected_stays_rejected": True,
    "document_tags_tenant_isolation": True,
    "document_tags_lifecycle": "reviewed_v1",
    "document_tags_b_is_experimental_semantic_alternative": True,
    "document_tags_automatic_tags_are_proposals": True,
    "document_tags_user_label_distinct_from_extracted_property": True,
    "document_tags_a_is_cheap_ingest_candidate": True,
    "document_tags_experiment": "closed_v1",
    "document_tags_do_not_run_more_jev_on_16_docs": True,
    "document_catalog_and_tabular_review_are_complementary": True,
    "document_catalog_reuses_canonical_document": True,
    "document_catalog_reuses_document_version": True,
    "document_catalog_do_not_import_overgraph_ingest": True,
}


def load_overgraph_search_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or SEARCH_BASELINE_PATH).read_text(encoding="utf-8"))


def load_jaccard_rejection(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or JACCARD_REJECTION_PATH).read_text(encoding="utf-8"))


def load_bge_m3_rejection(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or BGE_M3_REJECTION_PATH).read_text(encoding="utf-8"))


FIRST_EVIDENCE_BASELINE_ID = "phase2-first-verified-evidence"
FIRST_EVIDENCE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{FIRST_EVIDENCE_BASELINE_ID}.json"
)
EVIDENCE_CURVE_BASELINE_ID = "phase2-evidence-curve-v1"
EVIDENCE_CURVE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{EVIDENCE_CURVE_BASELINE_ID}.json"
)


def load_first_evidence_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or FIRST_EVIDENCE_BASELINE_PATH).read_text(encoding="utf-8"))


def load_evidence_curve_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or EVIDENCE_CURVE_BASELINE_PATH).read_text(encoding="utf-8"))


WORKSPACE_STOP_BASELINE_ID = "phase2-workspace-stop-replay-v1"
WORKSPACE_STOP_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{WORKSPACE_STOP_BASELINE_ID}.json"
)


def load_workspace_stop_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or WORKSPACE_STOP_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_GAP_BASELINE_ID = "phase2-proof-gap-v1"
PROOF_GAP_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_GAP_BASELINE_ID}.json"
)


def load_proof_gap_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_GAP_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_CONTRACT_BASELINE_ID = "phase2-proof-contract-v1"
PROOF_CONTRACT_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_CONTRACT_BASELINE_ID}.json"
)


def load_proof_contract_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_CONTRACT_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_WORK_BASELINE_ID = "phase2-proof-work-v1"
PROOF_WORK_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_WORK_BASELINE_ID}.json"
)


def load_proof_work_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_WORK_BASELINE_PATH).read_text(encoding="utf-8"))


RELATION_COVERAGE_BASELINE_ID = "phase2-coverage-v3-relation-carveout"
RELATION_COVERAGE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{RELATION_COVERAGE_BASELINE_ID}.json"
)


def load_relation_coverage_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or RELATION_COVERAGE_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_LINK_BASELINE_ID = "phase2-proof-link-v1"
PROOF_LINK_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_LINK_BASELINE_ID}.json"
)


def load_proof_link_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_LINK_BASELINE_PATH).read_text(encoding="utf-8"))


LINK_COVERAGE_BASELINE_ID = "phase2-coverage-v3-link-carveout"
LINK_COVERAGE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{LINK_COVERAGE_BASELINE_ID}.json"
)


def load_link_coverage_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LINK_COVERAGE_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_MORPH_BASELINE_ID = "phase2-proof-morph-v1"
PROOF_MORPH_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_MORPH_BASELINE_ID}.json"
)


def load_proof_morph_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_MORPH_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_JEV_BASELINE_ID = "phase2-proof-jev-morph-v1"
PROOF_JEV_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_JEV_BASELINE_ID}.json"
)


def load_proof_jev_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_JEV_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_GATE_BASELINE_ID = "phase2-proof-gate-v1"
PROOF_GATE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_GATE_BASELINE_ID}.json"
)


def load_proof_gate_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_GATE_BASELINE_PATH).read_text(encoding="utf-8"))


GATE_COVERAGE_BASELINE_ID = "phase2-coverage-v3-gate-carveout"
GATE_COVERAGE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{GATE_COVERAGE_BASELINE_ID}.json"
)


def load_gate_coverage_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or GATE_COVERAGE_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_FOUND_BASELINE_ID = "phase2-proof-found-v1"
PROOF_FOUND_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_FOUND_BASELINE_ID}.json"
)


def load_proof_found_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_FOUND_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_EVIDENCE_BASELINE_ID = "phase2-proof-evidence-v1"
PROOF_EVIDENCE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_EVIDENCE_BASELINE_ID}.json"
)


def load_proof_evidence_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_EVIDENCE_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_LOGIC_BASELINE_ID = "phase2-proof-logic-v1"
PROOF_LOGIC_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_LOGIC_BASELINE_ID}.json"
)


def load_proof_logic_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_LOGIC_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_PREDICATE_BASELINE_ID = "phase2-proof-predicate-v1"
PROOF_PREDICATE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_PREDICATE_BASELINE_ID}.json"
)


def load_proof_predicate_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_PREDICATE_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_PROPOSED_BASELINE_ID = "phase2-proof-proposed-v1"
PROOF_PROPOSED_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_PROPOSED_BASELINE_ID}.json"
)


def load_proof_proposed_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_PROPOSED_BASELINE_PATH).read_text(encoding="utf-8"))


BLIND_CARVEOUT_BASELINE_ID = "phase2-blind-carveout-gold-v1"
BLIND_CARVEOUT_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{BLIND_CARVEOUT_BASELINE_ID}.json"
)


def load_blind_carveout_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or BLIND_CARVEOUT_BASELINE_PATH).read_text(encoding="utf-8"))


DECISION_TRACE_BASELINE_ID = "phase2-decision-trace-v1"
DECISION_TRACE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DECISION_TRACE_BASELINE_ID}.json"
)


def load_decision_trace_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DECISION_TRACE_BASELINE_PATH).read_text(encoding="utf-8"))


BLIND_TRACE_RUN_BASELINE_ID = "phase2-coverage-v3-blind-trace-v1"
BLIND_TRACE_RUN_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{BLIND_TRACE_RUN_BASELINE_ID}.json"
)


def load_blind_trace_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or BLIND_TRACE_RUN_BASELINE_PATH).read_text(encoding="utf-8"))


PROOF_REQUIREMENTS_BASELINE_ID = "phase2-proof-requirements-v1"
PROOF_REQUIREMENTS_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PROOF_REQUIREMENTS_BASELINE_ID}.json"
)


def load_proof_requirements_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PROOF_REQUIREMENTS_BASELINE_PATH).read_text(encoding="utf-8"))


GOLD_MAP_BASELINE_ID = "phase2-gold-map-v2"
GOLD_MAP_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{GOLD_MAP_BASELINE_ID}.json"
)


def load_gold_map_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or GOLD_MAP_BASELINE_PATH).read_text(encoding="utf-8"))


DECISION_CONTRACT_BASELINE_ID = "phase2-decision-contract-v1"
DECISION_CONTRACT_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DECISION_CONTRACT_BASELINE_ID}.json"
)


def load_decision_contract_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DECISION_CONTRACT_BASELINE_PATH).read_text(encoding="utf-8"))


CLAUSE_RESOLVE_BASELINE_ID = "phase2-clause-resolve-v1"
CLAUSE_RESOLVE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CLAUSE_RESOLVE_BASELINE_ID}.json"
)


def load_clause_resolve_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CLAUSE_RESOLVE_BASELINE_PATH).read_text(encoding="utf-8"))


ANAPHOR_LIST_BASELINE_ID = "phase2-anaphor-list-v1"
ANAPHOR_LIST_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{ANAPHOR_LIST_BASELINE_ID}.json"
)


def load_anaphor_list_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or ANAPHOR_LIST_BASELINE_PATH).read_text(encoding="utf-8"))


ABILITY_CURVE_BASELINE_ID = "phase2-ability-curve-v1"
ABILITY_CURVE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{ABILITY_CURVE_BASELINE_ID}.json"
)


def load_ability_curve_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or ABILITY_CURVE_BASELINE_PATH).read_text(encoding="utf-8"))


LEFTOVER_DIAGNOSIS_BASELINE_ID = "phase2-leftover-diagnosis-v1"
LEFTOVER_DIAGNOSIS_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{LEFTOVER_DIAGNOSIS_BASELINE_ID}.json"
)


def load_leftover_diagnosis_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LEFTOVER_DIAGNOSIS_BASELINE_PATH).read_text(encoding="utf-8"))


ABILITY_REVIEW_BASELINE_ID = "phase2-ability-review-v1"
ABILITY_REVIEW_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{ABILITY_REVIEW_BASELINE_ID}.json"
)


def load_ability_review_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or ABILITY_REVIEW_BASELINE_PATH).read_text(encoding="utf-8"))


STATIC_REVIEW_BASELINE_ID = "phase2-static-review-v1"
STATIC_REVIEW_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{STATIC_REVIEW_BASELINE_ID}.json"
)


def load_static_review_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or STATIC_REVIEW_BASELINE_PATH).read_text(encoding="utf-8"))


EXPERIMENT_PRINCIPLES_BASELINE_ID = "phase2-experiment-principles-v1"
EXPERIMENT_PRINCIPLES_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{EXPERIMENT_PRINCIPLES_BASELINE_ID}.json"
)


def load_experiment_principles_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or EXPERIMENT_PRINCIPLES_BASELINE_PATH).read_text(encoding="utf-8"))


CITATION_LABEL_BASELINE_ID = "phase2-citation-label-v1"
CITATION_LABEL_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CITATION_LABEL_BASELINE_ID}.json"
)


def load_citation_label_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CITATION_LABEL_BASELINE_PATH).read_text(encoding="utf-8"))


LEFTOVER_29_BASELINE_ID = "phase2-leftover-29-v1"
LEFTOVER_29_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{LEFTOVER_29_BASELINE_ID}.json"
)


def load_leftover_29_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LEFTOVER_29_BASELINE_PATH).read_text(encoding="utf-8"))


DISCOVERY_DIAGNOSIS_BASELINE_ID = "phase2-discovery-diagnosis-v1"
DISCOVERY_DIAGNOSIS_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DISCOVERY_DIAGNOSIS_BASELINE_ID}.json"
)


def load_discovery_diagnosis_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DISCOVERY_DIAGNOSIS_BASELINE_PATH).read_text(encoding="utf-8"))


TWO_STAGE_RETRIEVAL_BASELINE_ID = "phase2-two-stage-retrieval-v1"
TWO_STAGE_RETRIEVAL_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TWO_STAGE_RETRIEVAL_BASELINE_ID}.json"
)


def load_two_stage_retrieval_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TWO_STAGE_RETRIEVAL_BASELINE_PATH).read_text(encoding="utf-8"))


WORKSPACE_INVENTORY_BASELINE_ID = "phase2-workspace-inventory-v1"
WORKSPACE_INVENTORY_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{WORKSPACE_INVENTORY_BASELINE_ID}.json"
)


def load_workspace_inventory_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or WORKSPACE_INVENTORY_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_RERANK_BASELINE_ID = "phase2-cerebras-rerank-v1"
CEREBRAS_RERANK_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_RERANK_BASELINE_ID}.json"
)


def load_cerebras_rerank_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_RERANK_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_OUTPUT_BASELINE_ID = "phase2-cerebras-output-v1"
CEREBRAS_OUTPUT_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_OUTPUT_BASELINE_ID}.json"
)


def load_cerebras_output_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_OUTPUT_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_QWEN_BASELINE_ID = "phase2-cerebras-qwen-v1"
CEREBRAS_QWEN_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_QWEN_BASELINE_ID}.json"
)


def load_cerebras_qwen_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_QWEN_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_REASONING_BASELINE_ID = "phase2-cerebras-reasoning-v1"
CEREBRAS_REASONING_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_REASONING_BASELINE_ID}.json"
)


def load_cerebras_reasoning_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_REASONING_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_CHOSEN_BASELINE_ID = "phase2-cerebras-medium-chosen-v1"
CEREBRAS_CHOSEN_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_CHOSEN_BASELINE_ID}.json"
)


def load_cerebras_chosen_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_CHOSEN_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_K100_BASELINE_ID = "phase2-cerebras-k100-v1"
CEREBRAS_K100_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_K100_BASELINE_ID}.json"
)


def load_cerebras_k100_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_K100_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_SPLIT50_BASELINE_ID = "phase2-cerebras-split50-v1"
CEREBRAS_SPLIT50_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_SPLIT50_BASELINE_ID}.json"
)


def load_cerebras_split50_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_SPLIT50_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_MODES_BASELINE_ID = "phase2-cerebras-modes-v1"
CEREBRAS_MODES_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{CEREBRAS_MODES_BASELINE_ID}.json"
)


def load_cerebras_modes_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_MODES_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_SECOND_OPINION_BASELINE_ID = "phase2-cerebras-second-opinion-v1"
CEREBRAS_SECOND_OPINION_BASELINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "baselines"
    / f"{CEREBRAS_SECOND_OPINION_BASELINE_ID}.json"
)


def load_cerebras_second_opinion_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_SECOND_OPINION_BASELINE_PATH).read_text(encoding="utf-8"))


CEREBRAS_ESCALATION_BASELINE_ID = "phase2-cerebras-second-opinion-rejected-v1"
CEREBRAS_ESCALATION_BASELINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "baselines"
    / f"{CEREBRAS_ESCALATION_BASELINE_ID}.json"
)


def load_cerebras_escalation_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CEREBRAS_ESCALATION_BASELINE_PATH).read_text(encoding="utf-8"))


PHASE_CLOSE_BASELINE_ID = "phase2-phase-close-v1"
PHASE_CLOSE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{PHASE_CLOSE_BASELINE_ID}.json"
)


def load_phase_close_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or PHASE_CLOSE_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_REVIEW_BASELINE_ID = "phase2-tabular-review-v1"
TABULAR_REVIEW_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_REVIEW_BASELINE_ID}.json"
)


def load_tabular_review_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_REVIEW_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_QWEN_BASELINE_ID = "phase2-tabular-qwen-v1"
TABULAR_QWEN_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_QWEN_BASELINE_ID}.json"
)


def load_tabular_qwen_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_QWEN_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_CITATION_BASELINE_ID = "phase2-tabular-citation-v1"
TABULAR_CITATION_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_CITATION_BASELINE_ID}.json"
)


def load_tabular_citation_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_CITATION_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_K10_BASELINE_ID = "phase2-tabular-k10-v1"
TABULAR_K10_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_K10_BASELINE_ID}.json"
)


def load_tabular_k10_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_K10_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_K10_ERRORS_BASELINE_ID = "phase2-tabular-k10-errors-v1"
TABULAR_K10_ERRORS_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_K10_ERRORS_BASELINE_ID}.json"
)


def load_tabular_k10_errors_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_K10_ERRORS_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_DIRECT_BASELINE_ID = "phase2-tabular-direct-v1"
TABULAR_DIRECT_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_DIRECT_BASELINE_ID}.json"
)


def load_tabular_direct_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_DIRECT_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_SIGNALS_BASELINE_ID = "phase2-tabular-signals-v1"
TABULAR_SIGNALS_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_SIGNALS_BASELINE_ID}.json"
)


def load_tabular_signals_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_SIGNALS_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_DENSE_BASELINE_ID = "phase2-tabular-dense-v1"
TABULAR_DENSE_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_DENSE_BASELINE_ID}.json"
)


def load_tabular_dense_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_DENSE_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_DENSE_ERRORS_BASELINE_ID = "phase2-tabular-dense-errors-v1"
TABULAR_DENSE_ERRORS_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_DENSE_ERRORS_BASELINE_ID}.json"
)


def load_tabular_dense_errors_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_DENSE_ERRORS_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_PROMPT_DEV_BASELINE_ID = "phase2-tabular-prompt-dev-v1"
TABULAR_PROMPT_DEV_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_PROMPT_DEV_BASELINE_ID}.json"
)


def load_tabular_prompt_dev_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_PROMPT_DEV_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_PROMPT_EN_BASELINE_ID = "phase2-tabular-prompt-en-v1"
TABULAR_PROMPT_EN_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_PROMPT_EN_BASELINE_ID}.json"
)


def load_tabular_prompt_en_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_PROMPT_EN_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_STATUS_V2_BASELINE_ID = "phase2-tabular-status-v2"
TABULAR_STATUS_V2_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_STATUS_V2_BASELINE_ID}.json"
)


def load_tabular_status_v2_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_STATUS_V2_BASELINE_PATH).read_text(encoding="utf-8"))


TABULAR_STATUS_V2_REPEATS_ID = "phase2-tabular-status-v2-repeats"
TABULAR_STATUS_V2_REPEATS_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_STATUS_V2_REPEATS_ID}.json"
)


def load_tabular_status_v2_repeats_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_STATUS_V2_REPEATS_PATH).read_text(encoding="utf-8"))


TABULAR_PROBABILITY_ID = "phase2-tabular-jev-probability-v1"
TABULAR_PROBABILITY_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_PROBABILITY_ID}.json"
)


def load_tabular_probability_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_PROBABILITY_PATH).read_text(encoding="utf-8"))


TABULAR_QUESTION_GOLD_ID = "phase2-tabular-question-gold-v1"
TABULAR_QUESTION_GOLD_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_QUESTION_GOLD_ID}.json"
)


def load_tabular_question_gold_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_QUESTION_GOLD_PATH).read_text(encoding="utf-8"))


TABULAR_USER_GOLD_ID = "phase2-tabular-user-gold-v1"
TABULAR_USER_GOLD_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_USER_GOLD_ID}.json"
)


def load_tabular_user_gold_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_USER_GOLD_PATH).read_text(encoding="utf-8"))


TABULAR_HOLD_OUT_GOLD_ID = "phase2-tabular-holdout-gold-v1"
TABULAR_HOLD_OUT_GOLD_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_HOLD_OUT_GOLD_ID}.json"
)


def load_tabular_holdout_gold_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_HOLD_OUT_GOLD_PATH).read_text(encoding="utf-8"))


TABULAR_HOLD_OUT_RUN_ID = "phase2-tabular-holdout-run-v1"
TABULAR_HOLD_OUT_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_HOLD_OUT_RUN_ID}.json"
)


def load_tabular_holdout_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_HOLD_OUT_RUN_PATH).read_text(encoding="utf-8"))


TABULAR_ENRICH_ID = "phase2-tabular-enrich-v1"
TABULAR_ENRICH_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_ENRICH_ID}.json"
)


def load_tabular_enrich_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_ENRICH_PATH).read_text(encoding="utf-8"))


TABULAR_ENRICH_RUN_ID = "phase2-tabular-enrich-run-v1"
TABULAR_ENRICH_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_ENRICH_RUN_ID}.json"
)


def load_tabular_enrich_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_ENRICH_RUN_PATH).read_text(encoding="utf-8"))


TABULAR_ENRICH_REJECT_ID = "phase2-tabular-enrich-reject-v1"
TABULAR_ENRICH_REJECT_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_ENRICH_REJECT_ID}.json"
)


def load_tabular_enrich_reject_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_ENRICH_REJECT_PATH).read_text(encoding="utf-8"))


TABULAR_PRESENT_ID = "phase2-tabular-present-v1"
TABULAR_PRESENT_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_PRESENT_ID}.json"
)


def load_tabular_present_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_PRESENT_PATH).read_text(encoding="utf-8"))


TABULAR_PRESENT_RUN_ID = "phase2-tabular-present-run-v1"
TABULAR_PRESENT_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_PRESENT_RUN_ID}.json"
)


def load_tabular_present_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_PRESENT_RUN_PATH).read_text(encoding="utf-8"))


TABULAR_PRESENT_REJECT_ID = "phase2-tabular-present-reject-v1"
TABULAR_PRESENT_REJECT_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_PRESENT_REJECT_ID}.json"
)


def load_tabular_present_reject_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_PRESENT_REJECT_PATH).read_text(encoding="utf-8"))


TABULAR_MULTI_RUN_ID = "phase2-tabular-multi-run-v1"
TABULAR_MULTI_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{TABULAR_MULTI_RUN_ID}.json"
)


def load_tabular_multi_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or TABULAR_MULTI_RUN_PATH).read_text(encoding="utf-8"))


DOCTYPE_GOLD_ID = "phase2-doctype-gold-v1"
DOCTYPE_GOLD_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DOCTYPE_GOLD_ID}.json"
)


def load_doctype_gold_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DOCTYPE_GOLD_PATH).read_text(encoding="utf-8"))


DOCTYPE_RUN_ID = "phase2-doctype-run-v1"
DOCTYPE_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DOCTYPE_RUN_ID}.json"
)


def load_doctype_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DOCTYPE_RUN_PATH).read_text(encoding="utf-8"))


DOCUMENT_TAGS_GOLD_ID = "phase2-document-tags-gold-v1"
DOCUMENT_TAGS_GOLD_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DOCUMENT_TAGS_GOLD_ID}.json"
)


def load_document_tags_gold_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DOCUMENT_TAGS_GOLD_PATH).read_text(encoding="utf-8"))


DOCUMENT_TAGS_RUN_ID = "phase2-document-tags-v1"
DOCUMENT_TAGS_RUN_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DOCUMENT_TAGS_RUN_ID}.json"
)


def load_document_tags_run_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DOCUMENT_TAGS_RUN_PATH).read_text(encoding="utf-8"))


DOCUMENT_TAGS_LIFECYCLE_ID = "phase2-document-tags-lifecycle-v1"
DOCUMENT_TAGS_LIFECYCLE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DOCUMENT_TAGS_LIFECYCLE_ID}.json"
)


def load_document_tags_lifecycle_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DOCUMENT_TAGS_LIFECYCLE_PATH).read_text(encoding="utf-8"))


DOCUMENT_TAGS_CLOSE_ID = "phase2-document-tags-close-v1"
DOCUMENT_TAGS_CLOSE_PATH = (
    Path(__file__).resolve().parents[2] / "baselines" / f"{DOCUMENT_TAGS_CLOSE_ID}.json"
)


def load_document_tags_close_baseline(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or DOCUMENT_TAGS_CLOSE_PATH).read_text(encoding="utf-8"))
