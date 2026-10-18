"""Close the measured phase: which abilities may leave the bench, which stay."""

from __future__ import annotations

import json
from pathlib import Path

from overgraph_ingest.coverage.leftover_29 import QUALITY_REFERENCE
from overgraph_ingest.retrieval.gold_map import GOLD_MAP_VERSION

ROOT = Path(__file__).resolve().parents[1]
PHASE_CLOSE_ID = "phase2-phase-close-v1"
PHASE_CLOSE_PATH = ROOT / "baselines" / f"{PHASE_CLOSE_ID}.json"


def freeze_phase_close() -> dict[str, object]:
    return {
        "id": PHASE_CLOSE_ID,
        "label": (
            "Frozen close of the measured OverGraph ingest phase. The bench "
            "separates fast clause search, document coverage, and legal proof. "
            "That split is the result. Do not transfer experimental proof "
            "rules or a model router into Socialism. Do not start the next "
            "ability from this file. 24/53 remains the quality reference."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "applied_to_v3": False,
        "does_not_start_next_ability": True,
        "does_not_start_socialism_integration": True,
        "does_not_build_model_router": True,
        "k200_not_started": True,
        "same_mapping": GOLD_MAP_VERSION,
        "original_goal": "analyse_200_contracts_quickly",
        "measured_split": (
            "fast_clause_search",
            "document_coverage",
            "legal_proof_evaluation",
        ),
        "headline": {
            "quality_reference": QUALITY_REFERENCE,
            "consider_for_socialism": [
                {
                    "ability": "docx_ingest",
                    "status": "consider",
                    "why": "Official sequential 100-DOCX ingest is closed and stable.",
                    "source": "phase1-sequential-100-docx",
                },
                {
                    "ability": "hybrid_search",
                    "status": "consider",
                    "why": "Default retriever is openai-tfidf. Engine search is not to be optimized from this bench.",
                    "source": "phase2-overgraph-hybrid-search",
                },
                {
                    "ability": "jev_c8_classify",
                    "status": "consider",
                    "why": "One TextUnit per prompt, concurrency 8, remains the economic classify reference.",
                    "source": "phase2-jev-classify-c8",
                },
            ],
            "keep_as_research": [
                {
                    "ability": "coverage_v3",
                    "status": "research",
                    "why": "Hop-always is not proof. Workspace inventory is unsolved and expensive.",
                    "source": "phase2-coverage-v3-blind-trace-v1",
                },
                {
                    "ability": "proof_evaluation",
                    "status": "research",
                    "why": "Formulation presence is not prevailing terms. Experimental proof rules are not production.",
                    "source": "phase2-experiment-principles-v1",
                },
                {
                    "ability": "cerebras_naive_rerank",
                    "status": "research",
                    "why": "Useful for reading a larger candidate list. Measured on five questions. Does not replace Jev.",
                    "source": "phase2-cerebras-modes-v1",
                },
            ],
            "rejected": [
                {
                    "ability": "second_opinion_escalation",
                    "verdict": "rejected_for_general_escalation",
                    "source": "phase2-cerebras-second-opinion-rejected-v1",
                },
                {
                    "ability": "qwen_naive_rerank",
                    "verdict": "rejected_for_naive_rerank",
                    "source": "phase2-cerebras-qwen-v1",
                },
                {
                    "ability": "bge_m3",
                    "verdict": "rejected",
                    "source": "phase2-bge-m3-rejected",
                },
                {
                    "ability": "jaccard_expansion_routing",
                    "verdict": "rejected",
                    "source": "phase2-jaccard-expansion-routing-rejected",
                },
                {
                    "ability": "jev_prompt_batching",
                    "verdict": "rejected_for_classify",
                    "source": "phase2-jev-classify-c8",
                },
                {
                    "ability": "jev_standalone_proof",
                    "verdict": "rejected_for_standalone",
                    "source": "phase2-proof-jev-morph-v1",
                },
            ],
            "do_not_start": [
                "k200",
                "model_router",
                "automatic_k_routing",
                "majority_vote",
                "uncertain_escalation",
                "socialism_integration",
                "default_controller_change",
            ],
        },
    }


def write_phase_close(path: Path | None = None) -> Path:
    target = path or PHASE_CLOSE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_phase_close(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
