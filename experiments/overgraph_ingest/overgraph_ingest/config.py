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
    coverage_query_variant: str = "baseline"
    coverage_gold_ids: tuple[str, ...] = ()
    coverage_v3_baseline: Path | None = None

    def resolved_cache_dir(self) -> Path:
        if self.cache_dir is not None:
            return self.cache_dir
        return self.db_path.parent / "extract-cache"
