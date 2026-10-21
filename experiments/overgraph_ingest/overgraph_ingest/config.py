"""CLI-driven ingest settings. No environment reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class JevRunConfig:
    db_path: Path
    gold_path: Path | None = None
    candidates_path: Path | None = None
    dense_dimension: int | None = None
    typesafe_api_key: str | None = None
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    experiment: str = "A"
    batch_size: int = 1
    concurrency: int = 8
    candidate_strategy: str = "hybrid"
    candidate_k: int = 50
    timeout_seconds: float = 8.0
    baseline_path: Path | None = None


@dataclass(frozen=True)
class RetrievalConfig:
    db_path: Path
    gold_path: Path | None = None
    dense_dimension: int | None = None
    write_batch_size: int = 500
    dense_model: str = "text-embedding-3-large"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    embed: bool = False
    fusion_mode: str = "reciprocal_rank"
    ks: tuple[int, ...] = (5, 10, 20, 50, 100)


@dataclass(frozen=True)
class IngestConfig:
    db_path: Path
    input_dir: Path | None = None
    cache_dir: Path | None = None
    collection_id: str = "contracts"
    dense_dimension: int | None = None
    write_batch_size: int = 500
    target_chars: int = 1200
    max_chars: int = 2400
    extraction_version: str = "extract-v1"
    segmentation_version: str = "structural-v1"
    benchmark: bool = False
    verify_only: bool = False
    output_path: Path | None = None
    generate_corpus: int | None = None
    limit: int | None = None
    suite: bool = False
    repeats: int = 5
    gold_dir: Path | None = None
    real_gold_dir: Path | None = None
    graph_only: bool = False
    batch_sweep: bool = False
    retrieve_gold: Path | None = None
    embed: bool = False
    dense_model: str = "text-embedding-3-large"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    fusion_mode: str = "reciprocal_rank"
    ks: tuple[int, ...] = field(default=(5, 10, 20, 50, 100))
    classify_jev: bool = False
    candidates_path: Path | None = None
    typesafe_api_key: str | None = None
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    jev_experiment: str = "A"
    jev_batch_size: int = 1
    jev_concurrency: int = 8
    jev_timeout_seconds: float = 8.0
    jev_baseline_path: Path | None = None
    candidate_strategy: str = "hybrid"
    candidate_k: int = 50
    navigate: bool = False
    coverage: bool = False
    coverage_global_k: int = 50
    coverage_per_document: tuple[int, ...] = (3, 5)
    coverage_v2: bool = False
    coverage_v2_passes: int = 3
    coverage_v3: bool = False
    coverage_budgets: tuple[int | None, ...] = (1, 2, 3, 5)
    expand_queries: bool = False
    profile_retrieval: bool = False
    decide_expansion: bool = False
    compare_embeddings: bool = False
    analysis_cost: bool = False
    evidence_curve: bool = False
    workspace_stop_replay: bool = False
    proof_gap: bool = False
    proof_contract: bool = False
    proof_work: bool = False
    proof_link: bool = False
    proof_morph: bool = False
    proof_jev: bool = False
    proof_gate: bool = False
    proof_found: bool = False
    proof_evidence: bool = False
    proof_logic: bool = False
    proof_predicate: bool = False
    proof_proposed: bool = False
    blind_carveout: bool = False
    coverage_query_variant: str = "baseline"
    coverage_gold_ids: tuple[str, ...] = ()
    coverage_v3_baseline: Path | None = None
    proof_rule: str = "current"
    coverage_proof_gate: bool = False
    decision_trace: bool = False
    inspect_decision_trace: bool = False
    proof_requirements: bool = False
    gold_map_v2: bool = False
    decision_contract: bool = False
    clause_resolve: bool = False
    anaphor_resolve: bool = False
    leftover_diagnosis: bool = False
    citation_labels: bool = False
    discovery_diagnosis: bool = False
    two_stage_retrieval: bool = False
    cerebras_rerank: bool = False
    cerebras_api_key: str | None = None
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_model: str = "gpt-oss-120b"
    cerebras_k: int = 50
    cerebras_output: bool = False
    cerebras_qwen: bool = False
    cerebras_reasoning: bool = False
    cerebras_k100: bool = False
    cerebras_split50: bool = False
    cerebras_second_opinion: bool = False
    tabular_review: bool = False
    tabular_qwen: bool = False
    tabular_citation: bool = False
    tabular_k10: bool = False
    tabular_k10_errors: bool = False
    tabular_direct: bool = False
    tabular_signals: bool = False
    tabular_dense: bool = False
    tabular_dense_errors: bool = False
    tabular_prompt_dev: bool = False
    tabular_prompt_en: bool = False
    tabular_status_v2: bool = False
    tabular_status_v2_repeats: bool = False
    tabular_probability: bool = False
    tabular_question_gold: bool = False
    tabular_user_gold: bool = False
    tabular_holdout: bool = False
    tabular_holdout_run: bool = False
    tabular_enrich: bool = False
    tabular_enrich_run: bool = False
    tabular_enrich_reject: bool = False
    tabular_present: bool = False
    tabular_present_run: bool = False
    tabular_present_reject: bool = False
    tabular_multi_run: bool = False
    doctype_gold: bool = False
    doctype_run: bool = False
    document_tags_gold: bool = False
    document_tags_run: bool = False
    document_tags_lifecycle: bool = False
    document_tags_close: bool = False
    bm25_compare: bool = False
    bm25_scope: str = "both"
    bm25_analyzer: str = "sv_stem_v1"
    bm25_index_dir: Path | None = None
    bm25_branch_depth: int = 100
    bm25_local_ks: tuple[int, ...] = (1, 3, 5, 10)
    bm25_paging: bool = False
    bm25_page_size: int = 20
    bm25_answer_test: bool = False
    bm25_candidates: Path | None = None
    bm25_repeats: int = 20
    bm25_gold_dir: Path | None = None
    bm25_question_gold: Path | None = None
    bm25_rebuild_index: bool = False
    discovery_test: bool = False
    document_properties: bool = False
    property_track: str = "structure"
    property_taxonomy: Path | None = None
    property_gold_mapping: Path | None = None
    property_bm25_run: Path | None = None
    jev_property_verification: bool = False
    jev_property_review: Path | None = None
    jev_end_to_end: bool = False
    jev_local_k: int = 5
    jev_local_abc: bool = False
    jev_local_baseline: Path | None = None
    jev_evidence_queries: Path | None = None
    jev_presentation: bool = False
    jev_validation: bool = False
    freeze_baseline: bool = False

    def resolved_cache_dir(self) -> Path:
        if self.cache_dir is not None:
            return self.cache_dir
        return self.db_path.parent / "extract-cache"
