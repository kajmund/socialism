"""CLI for the standalone OverGraph ingest experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from overgraph_ingest.benchmarks.corpus import generate_corpus
from overgraph_ingest.benchmarks.report import report_payload, write_report
from overgraph_ingest.benchmarks.suite import run_suite
from overgraph_ingest.config import IngestConfig, JevRunConfig, RetrievalConfig
from overgraph_ingest.jev.run import run_jev_classification
from overgraph_ingest.coverage.run import run_coverage
from overgraph_ingest.coverage.v2 import run_coverage_v2
from overgraph_ingest.coverage.compare import compare_v3_golds
from overgraph_ingest.coverage.v3 import run_coverage_v3
from overgraph_ingest.coverage.analysis_cost import run_analysis_cost
from overgraph_ingest.coverage.evidence_curve import run_evidence_curves
from overgraph_ingest.coverage.stop_replay import run_stop_replay
from overgraph_ingest.coverage.proof_gap import run_proof_gap
from overgraph_ingest.coverage.proof_contract import run_proof_contract
from overgraph_ingest.coverage.proof_work import run_proof_work
from overgraph_ingest.coverage.proof_link_run import run_proof_link
from overgraph_ingest.coverage.proof_morph import run_proof_morph
from overgraph_ingest.coverage.evidence_run import run_proof_evidence
from overgraph_ingest.coverage.logic_run import run_proof_logic
from overgraph_ingest.coverage.predicate_run import run_proof_predicate
from overgraph_ingest.coverage.blind_carveout import run_blind_carveout
from overgraph_ingest.coverage.decision_trace_run import run_decision_trace
from overgraph_ingest.coverage.proof_requirements import run_proof_requirements
from overgraph_ingest.coverage.chain_run import run_decision_contract
from overgraph_ingest.coverage.anaphor_run import run_anaphor_resolve
from overgraph_ingest.coverage.clause_run import run_clause_resolve
from overgraph_ingest.coverage.leftover_run import run_leftover_diagnosis
from overgraph_ingest.coverage.citation_run import run_citation_labels
from overgraph_ingest.coverage.leftover_discovery import run_discovery_diagnosis
from overgraph_ingest.retrieval.two_stage import run_two_stage_retrieval
from overgraph_ingest.cerebras.k100 import run_cerebras_k100
from overgraph_ingest.cerebras.second_opinion import run_cerebras_second_opinion
from overgraph_ingest.tabular.run import run_tabular_review
from overgraph_ingest.tabular.qwen import run_tabular_qwen
from overgraph_ingest.tabular.citation import run_tabular_citation
from overgraph_ingest.tabular.k10 import run_tabular_k10
from overgraph_ingest.tabular.k10_errors import run_tabular_k10_errors
from overgraph_ingest.tabular.direct import run_tabular_direct
from overgraph_ingest.tabular.signals import run_tabular_signals
from overgraph_ingest.tabular.dense import run_tabular_dense
from overgraph_ingest.tabular.dense_errors import run_tabular_dense_errors
from overgraph_ingest.tabular.prompt_dev import run_tabular_prompt_dev
from overgraph_ingest.tabular.prompt_en import run_tabular_prompt_en
from overgraph_ingest.tabular.status_v2 import run_tabular_status_v2
from overgraph_ingest.tabular.status_v2_repeats import run_tabular_status_v2_repeats
from overgraph_ingest.tabular.probability import run_tabular_probability
from overgraph_ingest.tabular.question_gold import review_question_gold
from overgraph_ingest.tabular.user_eval import compare_user_gold, write_user_gold_table
from overgraph_ingest.tabular.holdout_eval import review_holdout_gold, write_holdout_gold_table
from overgraph_ingest.tabular.holdout_run import (
    run_tabular_holdout,
    write_holdout_run_baseline,
    write_holdout_run_table,
)
from overgraph_ingest.tabular.enrich_eval import (
    review_enrich_protocol,
    write_enrich_protocol_baseline,
    write_enrich_protocol_table,
)
from overgraph_ingest.tabular.enrich_run import (
    run_tabular_enrich,
    write_enrich_run_baseline,
    write_enrich_run_table,
)
from overgraph_ingest.tabular.enrich_reject import (
    review_enrich_reject,
    write_enrich_reject_baseline,
    write_enrich_reject_table,
)
from overgraph_ingest.tabular.present_eval import (
    review_present_protocol,
    write_present_protocol_baseline,
    write_present_protocol_table,
)
from overgraph_ingest.tabular.present_run import (
    run_tabular_present,
    write_present_run_baseline,
    write_present_run_table,
)
from overgraph_ingest.tabular.present_reject import (
    review_present_reject,
    write_present_reject_baseline,
    write_present_reject_table,
)
from overgraph_ingest.tabular.multi_run import (
    run_tabular_multi,
    write_multi_run_baseline,
    write_multi_run_table,
)
from overgraph_ingest.doctype.gold_eval import (
    review_doctype_gold,
    write_doctype_gold_baseline,
    write_doctype_gold_table,
)
from overgraph_ingest.doctype.run import (
    run_doctype,
    write_doctype_run_baseline,
    write_doctype_run_table,
)
from overgraph_ingest.doctags.gold_eval import (
    review_document_tags_gold,
    write_document_tags_gold_baseline,
    write_document_tags_gold_table,
)
from overgraph_ingest.doctags.run import (
    run_document_tags,
    write_document_tags_run_baseline,
    write_document_tags_run_table,
)
from overgraph_ingest.doctags.lifecycle_eval import (
    run_document_tags_lifecycle,
    write_document_tags_lifecycle_baseline,
    write_document_tags_lifecycle_table,
)
from overgraph_ingest.doctags.close import (
    review_document_tags_close,
    write_document_tags_close_baseline,
    write_document_tags_close_table,
)
from overgraph_ingest.cerebras.split50 import run_cerebras_split50
from overgraph_ingest.cerebras.output import run_cerebras_output
from overgraph_ingest.cerebras.qwen import run_cerebras_qwen
from overgraph_ingest.cerebras.reasoning import run_cerebras_reasoning
from overgraph_ingest.cerebras.run import run_cerebras_rerank
from overgraph_ingest.retrieval.gold_map_run import run_gold_map
from overgraph_ingest.coverage.proposed_run import run_proof_proposed
from overgraph_ingest.coverage.proof_found import run_proof_found
from overgraph_ingest.coverage.proof_gate_run import run_proof_gate
from overgraph_ingest.coverage.proof_jev_run import run_proof_jev
from overgraph_ingest.jev.client import HttpJevClient
from overgraph_ingest.retrieval.compare_run import run_embedding_compare
from overgraph_ingest.retrieval.decide_run import run_expansion_decision
from overgraph_ingest.retrieval.expand_run import run_query_expansion
from overgraph_ingest.retrieval.profile import run_retrieval_profile
from overgraph_ingest.navigation.run import run_navigation
from overgraph_ingest.pipeline import prepare_documents, run_ingest, run_verify, write_prepared
from overgraph_ingest.quality.evaluate import evaluate_gold_dir, summarize_scores
from overgraph_ingest.quality.gold import generate_gold_set
from overgraph_ingest.retrieval.run import run_retrieval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OverGraph document ingest and retrieval")
    parser.add_argument("--input", type=Path, help="Directory of PDF/DOCX files")
    parser.add_argument("--db", type=Path, required=True, help="OverGraph directory")
    parser.add_argument("--cache-dir", type=Path, help="Extraction cache directory")
    parser.add_argument("--collection", default="contracts")
    parser.add_argument("--dense-dimension", type=int)
    parser.add_argument("--write-batch-size", type=int, default=500)
    parser.add_argument("--target-chars", type=int, default=1200)
    parser.add_argument("--max-chars", type=int, default=2400)
    parser.add_argument("--limit", type=int, help="Use only the first N discovered files")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, help="Benchmark JSON path")
    parser.add_argument("--generate-corpus", type=int, metavar="N")
    parser.add_argument("--suite", action="store_true", help="Run scaling, graph-only, and gold quality")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--gold", action="store_true", help="Generate and score the synthetic gold set")
    parser.add_argument("--gold-dir", type=Path)
    parser.add_argument("--real-gold", type=Path, help="Optional real contract directory")
    parser.add_argument("--graph-only", action="store_true", help="Write a prepared graph to a fresh database")
    parser.add_argument("--batch-sweep", action="store_true")
    parser.add_argument("--retrieve-gold", type=Path, help="Retrieval gold JSON")
    parser.add_argument("--embed", action="store_true", help="Write dense and sparse vectors before search")
    parser.add_argument("--dense-model", default="text-embedding-3-large")
    parser.add_argument("--openai-api-key", help="Required for text-embedding-3-large")
    parser.add_argument("--openai-base-url")
    parser.add_argument("--fusion-mode", default="reciprocal_rank")
    parser.add_argument("--k", default="5,10,20,50,100", help="Comma-separated k values")
    parser.add_argument("--classify-jev", action="store_true")
    parser.add_argument("--candidates", type=Path, help="Frozen retrieval JSON with hybrid hits")
    parser.add_argument("--typesafe-api-key")
    parser.add_argument("--typesafe-base-url", default="https://api.typesafe.ai")
    parser.add_argument("--jev-model", default="jev-latest")
    parser.add_argument("--jev-experiment", choices=("A", "B", "B1", "B2", "C", "E"), default="A")
    parser.add_argument("--jev-batch-size", type=int, default=1)
    parser.add_argument("--jev-concurrency", type=int, default=8)
    parser.add_argument("--jev-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--jev-baseline", type=Path, help="Experiment A JSON for flip comparison")
    parser.add_argument("--candidate-strategy", default="hybrid")
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument(
        "--navigate",
        action="store_true",
        help="Run the Avtal 46 and Avtal 49 hop measurements only",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run deterministic document coverage A/B/C without Jev",
    )
    parser.add_argument("--coverage-global-k", type=int, default=50)
    parser.add_argument(
        "--coverage-per-document",
        default="3,5",
        help="Comma-separated per-document depths for scoped and progressive",
    )
    parser.add_argument(
        "--coverage-v2",
        action="store_true",
        help="Run coverage v2: C@8 classify plus touched/fair deepen and measured hops",
    )
    parser.add_argument("--coverage-v2-passes", type=int, default=3)
    parser.add_argument(
        "--coverage-v3",
        action="store_true",
        help="Run coverage v3: per-document budget curves and proof-kind stop",
    )
    parser.add_argument(
        "--proof-rule",
        choices=("current", "relation", "link"),
        default="current",
        help="COMPOSITE proof rule. relation and link are experimental and do not replace v3.",
    )
    parser.add_argument(
        "--coverage-proof-gate",
        action="store_true",
        help="Admit EVIDENCE_FOUND only after the reference/polarity gate. Does not replace v3.",
    )
    parser.add_argument(
        "--coverage-budgets",
        default="1,2,3,5",
        help="Comma-separated per-document classify caps; 0 means unlimited",
    )
    parser.add_argument(
        "--expand-queries",
        action="store_true",
        help="Compare deterministic query expansion against the baseline query",
    )
    parser.add_argument(
        "--profile-retrieval",
        action="store_true",
        help="Isolate OverGraph engine search from Python exhaustive ranking",
    )
    parser.add_argument(
        "--decide-expansion",
        action="store_true",
        help="Compare never / always / dense-sparse disagreement. Does not change the default retriever.",
    )
    parser.add_argument(
        "--compare-embeddings",
        action="store_true",
        help="Compare OpenAI/BGE-M3 dense and sparse pairs. Does not write the official 3072 database.",
    )
    parser.add_argument(
        "--analysis-cost",
        action="store_true",
        help="Measure Jev work to first verified positive on frozen C@8 rankings",
    )
    parser.add_argument(
        "--evidence-curve",
        action="store_true",
        help="Verified-positive documents versus cumulative classifications from frozen runs",
    )
    parser.add_argument(
        "--workspace-stop-replay",
        action="store_true",
        help="Replay Coverage v3 timelines at workspace stop budgets. Does not change v3.",
    )
    parser.add_argument(
        "--proof-gap",
        action="store_true",
        help="Measure first signal to complete proof on frozen C@8 and Coverage v3",
    )
    parser.add_argument(
        "--proof-contract",
        action="store_true",
        help="Compare hop-always COMPOSITE with relation-in-text. Does not change v3.",
    )
    parser.add_argument(
        "--proof-work",
        action="store_true",
        help="Measure Rule B work on frozen C@8. Does not change v3 or claim 100 saved.",
    )
    parser.add_argument(
        "--proof-link",
        action="store_true",
        help="Test linked-relation proof evaluation. Does not change v3.",
    )
    parser.add_argument(
        "--proof-morph",
        action="store_true",
        help="Metamorphic clause variations. Does not change the detector or v3.",
    )
    parser.add_argument(
        "--proof-jev",
        action="store_true",
        help="Jev proof evaluation on morph cases. Does not change C@8 or v3.",
    )
    parser.add_argument(
        "--proof-gate",
        action="store_true",
        help="Reference integrity and polarity gate. Does not change C@8 or v3.",
    )
    parser.add_argument(
        "--proof-found",
        action="store_true",
        help="Replay EVIDENCE_FOUND for Avtal 12 and 60. No new Jev.",
    )
    parser.add_argument(
        "--proof-evidence",
        action="store_true",
        help="Validate source-grounded evidence proofs. Does not change v3.",
    )
    parser.add_argument(
        "--proof-logic",
        action="store_true",
        help="Polarity and scope as a logical form. Does not change v3.",
    )
    parser.add_argument(
        "--proof-predicate",
        action="store_true",
        help="Jev extracts a typed predicate. Does not decide SUPPORTED.",
    )
    parser.add_argument(
        "--proof-proposed",
        action="store_true",
        help="Diagnose the 17 proposed predicates. No new Jev.",
    )
    parser.add_argument(
        "--blind-carveout",
        action="store_true",
        help="Blind gold E versus seen detectors. No new Jev.",
    )
    parser.add_argument(
        "--decision-trace",
        action="store_true",
        help="Record EVIDENCE_FOUND unit traces. Does not change v3 stop or proof.",
    )
    parser.add_argument(
        "--inspect-decision-trace",
        action="store_true",
        help="Inspect saved coverage JSON for unit traces. No new Jev.",
    )
    parser.add_argument(
        "--proof-requirements",
        action="store_true",
        help="Regression requirements from observed traces. No new Jev.",
    )
    parser.add_argument(
        "--gold-map-v2",
        action="store_true",
        help="Locate gold with space-run collapse. Default contains unchanged.",
    )
    parser.add_argument(
        "--decision-contract",
        action="store_true",
        help="Rescore hop-always versus grounded-chain. Same gold-map v2.",
    )
    parser.add_argument(
        "--clause-resolve",
        action="store_true",
        help="Resolve explicit clause citations in the evidence chain.",
    )
    parser.add_argument(
        "--anaphor-resolve",
        action="store_true",
        help="Anchor anaphors and list items to a predication. Same gold-map v2.",
    )
    parser.add_argument(
        "--leftover-diagnosis",
        action="store_true",
        help="Distribute the 34 leftover gold YES. No new Jev.",
    )
    parser.add_argument(
        "--citation-labels",
        action="store_true",
        help="Recognize artikel, klausul, and roman citations. Same relation test.",
    )
    parser.add_argument(
        "--discovery-diagnosis",
        action="store_true",
        help="Diagnose why the 14 leftover YES never reached proof evaluation. No new Jev.",
    )
    parser.add_argument(
        "--two-stage-retrieval",
        action="store_true",
        help="Document-then-local retrieval at a fixed candidate budget. No Jev.",
    )
    parser.add_argument(
        "--cerebras-rerank",
        action="store_true",
        help="Naive Cerebras rerank of hybrid top-k. Formulation presence. No Jev.",
    )
    parser.add_argument(
        "--cerebras-api-key",
        help="Required for Cerebras rerank, output, Qwen, and reasoning runs",
    )
    parser.add_argument("--cerebras-base-url", default="https://api.cerebras.ai/v1")
    parser.add_argument("--cerebras-model", default="gpt-oss-120b")
    parser.add_argument("--cerebras-k", type=int, default=50)
    parser.add_argument(
        "--cerebras-output",
        action="store_true",
        help="Minimal Cerebras output on the frozen top-50. No new retrieval.",
    )
    parser.add_argument(
        "--cerebras-qwen",
        action="store_true",
        help="Qwen 3.8 27B on the frozen top-50 and minimal JSON. No new retrieval.",
    )
    parser.add_argument(
        "--cerebras-reasoning",
        action="store_true",
        help="GPT-OSS reasoning ablation on the frozen top-50. Off is unsupported.",
    )
    parser.add_argument(
        "--cerebras-k100",
        action="store_true",
        help="GPT-OSS medium, minimal JSON, hybrid top-100. No k=200.",
    )
    parser.add_argument(
        "--cerebras-split50",
        action="store_true",
        help="Hybrid top-100 as two sequential Medium calls of 50. No one-shot retry.",
    )
    parser.add_argument(
        "--cerebras-second-opinion",
        action="store_true",
        help="Replay Jev C@8 versus GPT-OSS on overlapping top-50 keys. No router.",
    )
    parser.add_argument(
        "--tabular-review",
        action="store_true",
        help="Document-local Tabular Review A/B/C. Sync cells. Not Coverage v3.",
    )
    parser.add_argument(
        "--tabular-qwen",
        action="store_true",
        help="Qwen 3.8 27B reasoning low on the frozen 100 Tabular cells. No new retrieval.",
    )
    parser.add_argument(
        "--tabular-citation",
        action="store_true",
        help="Replay saved Tabular cells: gold recall versus source selection. No new model.",
    )
    parser.add_argument(
        "--tabular-k10",
        action="store_true",
        help="Jev Tabular B at k=10 versus frozen B at k=5. No navigation.",
    )
    parser.add_argument(
        "--tabular-k10-errors",
        action="store_true",
        help="Replay k=10 gold-negative false answers. No new model.",
    )
    parser.add_argument(
        "--tabular-direct",
        action="store_true",
        help="One Jev answer_cell on frozen B k=5 keys. No classify. No navigation.",
    )
    parser.add_argument(
        "--tabular-signals",
        action="store_true",
        help="Dense vs sparse vs hybrid lists on frozen B cells. No answer_cell.",
    )
    parser.add_argument(
        "--tabular-dense",
        action="store_true",
        help="Jev answer_cell on frozen dense top-5. Hybrid D stays the reference.",
    )
    parser.add_argument(
        "--tabular-dense-errors",
        action="store_true",
        help="Replay D vs E false answers. No new model.",
    )
    parser.add_argument(
        "--tabular-prompt-dev",
        action="store_true",
        help="P0-P3 answer_cell instructions on the frozen development set.",
    )
    parser.add_argument(
        "--tabular-prompt-en",
        action="store_true",
        help="Same P0 instruction with English questions. Swedish P0 stays the reference.",
    )
    parser.add_argument(
        "--tabular-status-v2",
        action="store_true",
        help="P0 vs P0_v2 status definitions. Default P0 stays.",
    )
    parser.add_argument(
        "--tabular-status-v2-repeats",
        action="store_true",
        help="Repeat P0_v2_D and score unseen holdout. Default P0 stays.",
    )
    parser.add_argument(
        "--tabular-probability",
        action="store_true",
        help="Observe Jev choice confidence on tabular cells. Default P0 stays.",
    )
    parser.add_argument(
        "--tabular-question-gold",
        action="store_true",
        help="Diagnose user questions versus retrieval gold. No new model.",
    )
    parser.add_argument(
        "--tabular-user-gold",
        action="store_true",
        help="Score frozen D/E/K against question-oriented gold. No new model.",
    )
    parser.add_argument(
        "--tabular-holdout",
        action="store_true",
        help="Write holdout question gold. Does not run D, E, or K.",
    )
    parser.add_argument(
        "--tabular-holdout-run",
        action="store_true",
        help="Run locked holdout D/E/K on current ingest. One Jev. No ingest change.",
    )
    parser.add_argument(
        "--tabular-enrich",
        action="store_true",
        help="Freeze structure-aware embedding protocol. Baseline JSON needs --freeze-baseline. No encode. No Jev.",
    )
    parser.add_argument(
        "--tabular-enrich-run",
        action="store_true",
        help="Encode A vs B search texts and rank dense. No Jev.",
    )
    parser.add_argument(
        "--tabular-enrich-reject",
        action="store_true",
        help="Reject heading-enriched embeddings. Keep original search text.",
    )
    parser.add_argument(
        "--tabular-present",
        action="store_true",
        help="Freeze candidate-presentation protocol. Baseline JSON needs --freeze-baseline. Same five units. No Jev.",
    )
    parser.add_argument(
        "--tabular-present-run",
        action="store_true",
        help="Run text vs stored headings on development cells. Same five units. One Jev.",
    )
    parser.add_argument(
        "--tabular-present-reject",
        action="store_true",
        help="Reject heading metadata to Jev. Keep text-only answer_cell.",
    )
    parser.add_argument(
        "--tabular-multi-run",
        action="store_true",
        help="Run one cell answer vs a list on multi-span documents. Same five units. One Jev.",
    )
    parser.add_argument(
        "--doctype-gold",
        action="store_true",
        help="Freeze document-type gold. Baseline JSON needs --freeze-baseline. Principal function only. No Jev.",
    )
    parser.add_argument(
        "--doctype-run",
        action="store_true",
        help="Compare structure-only A with Jev B and wider-context C. Experiment only.",
    )
    parser.add_argument(
        "--document-tags-gold",
        action="store_true",
        help="Freeze document-tag gold. Baseline JSON needs --freeze-baseline. Limited classes. No Jev.",
    )
    parser.add_argument(
        "--document-tags-run",
        action="store_true",
        help="Compare structure-only tag A with Jev B. Experiment only.",
    )
    parser.add_argument(
        "--document-tags-lifecycle",
        action="store_true",
        help="Review tag lifecycle. No Jev. No new quality run.",
    )
    parser.add_argument(
        "--document-tags-close",
        action="store_true",
        help="Close the document-tag experiment. No Jev.",
    )
    parser.add_argument(
        "--freeze-baseline",
        action="store_true",
        help=(
            "Write experimental baseline JSONs for commands that freeze them. "
            "Off by default; existing baselines are never overwritten."
        ),
    )
    parser.add_argument(
        "--coverage-query-variant",
        choices=("baseline", "append"),
        default="baseline",
        help="Query text for coverage ranking. Does not change the default retriever.",
    )
    parser.add_argument(
        "--coverage-gold-id",
        action="append",
        default=[],
        help="Limit coverage to these gold ids. Repeatable.",
    )
    parser.add_argument(
        "--coverage-v3-baseline",
        type=Path,
        help="Frozen Coverage v3 JSON to compare against a treatment run",
    )
    parser.add_argument(
        "--bm25-compare",
        action="store_true",
        help="Opt-in Tantivy BM25 comparison. Step A is model-free retrieval.",
    )
    parser.add_argument(
        "--bm25-scope",
        choices=("global", "document", "both"),
        default="both",
        help="Run global inventory, document-local, or both BM25 scopes.",
    )
    parser.add_argument(
        "--bm25-analyzer",
        choices=("sv_stem_v1", "sv_plain_v1", "both"),
        default="sv_stem_v1",
        help="Tantivy analysis profile. Both also runs the plain control.",
    )
    parser.add_argument("--bm25-index-dir", type=Path)
    parser.add_argument("--bm25-branch-depth", type=int, default=100)
    parser.add_argument(
        "--bm25-local-ks",
        default="1,3,5,10",
        help="Comma-separated document-local final k values",
    )
    parser.add_argument(
        "--bm25-paging",
        action="store_true",
        help="Replay the frozen dense_bm25 list in pages of 20.",
    )
    parser.add_argument("--bm25-page-size", type=int, default=20)
    parser.add_argument(
        "--bm25-answer-test",
        action="store_true",
        help="Separate Step B: answer_cell on frozen candidates. Off by default.",
    )
    parser.add_argument("--bm25-candidates", type=Path)
    parser.add_argument("--bm25-repeats", type=int, default=20)
    parser.add_argument("--bm25-gold-dir", type=Path)
    parser.add_argument("--bm25-question-gold", type=Path)
    parser.add_argument(
        "--bm25-rebuild-index",
        action="store_true",
        help="Explicitly rebuild the derived BM25 index instead of reusing a match.",
    )
    parser.add_argument(
        "--discovery-test",
        action="store_true",
        help="Model-free document discovery diagnostic: aggregate TextUnit scores per document.",
    )
    parser.add_argument(
        "--document-properties",
        action="store_true",
        help="Track A document-property discovery: deterministic structure + frozen taxonomy.",
    )
    parser.add_argument(
        "--property-track",
        choices=("structure", "jev", "both"),
        default="structure",
        help="Which document-property track to run. Only structure is implemented first.",
    )
    parser.add_argument("--property-taxonomy", type=Path)
    parser.add_argument("--property-gold-mapping", type=Path)
    parser.add_argument("--property-bm25-run", type=Path)
    parser.add_argument(
        "--jev-property-verification",
        action="store_true",
        help="Jev verification of deterministic document properties. Isolated experiment.",
    )
    parser.add_argument(
        "--jev-property-review",
        type=Path,
        help="Per-entry review JSON with filled review.classification fields.",
    )
    parser.add_argument(
        "--jev-end-to-end",
        action="store_true",
        help="End-to-end document-property verification (discovery -> Jev -> local dense -> Jev).",
    )
    parser.add_argument("--jev-local-k", type=int, default=5)
    parser.add_argument(
        "--jev-local-abc",
        action="store_true",
        help="A/B/C comparison of the document-local dense query (evidence supplement).",
    )
    parser.add_argument("--jev-local-baseline", type=Path)
    parser.add_argument("--jev-evidence-queries", type=Path)
    parser.add_argument(
        "--jev-presentation",
        action="store_true",
        help="Presentation-fix experiment: show local dense top-5 clauses as primary Jev evidence.",
    )
    parser.add_argument(
        "--jev-validation",
        action="store_true",
        help="Broad validation of the Jev verification chain (111 FP + >=100 positives).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = IngestConfig(
        db_path=args.db,
        input_dir=args.input,
        cache_dir=args.cache_dir,
        collection_id=args.collection,
        dense_dimension=args.dense_dimension,
        write_batch_size=args.write_batch_size,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        benchmark=args.benchmark,
        verify_only=args.verify,
        output_path=args.output,
        generate_corpus=args.generate_corpus,
        limit=args.limit,
        suite=args.suite,
        repeats=args.repeats,
        gold_dir=args.gold_dir,
        real_gold_dir=args.real_gold,
        graph_only=args.graph_only,
        batch_sweep=args.batch_sweep,
        retrieve_gold=args.retrieve_gold,
        embed=args.embed,
        dense_model=args.dense_model,
        openai_api_key=args.openai_api_key,
        openai_base_url=args.openai_base_url,
        fusion_mode=args.fusion_mode,
        ks=_parse_ks(args.k),
        classify_jev=args.classify_jev,
        candidates_path=args.candidates,
        typesafe_api_key=args.typesafe_api_key,
        typesafe_base_url=args.typesafe_base_url,
        jev_model=args.jev_model,
        jev_experiment=args.jev_experiment,
        jev_batch_size=args.jev_batch_size,
        jev_concurrency=args.jev_concurrency,
        jev_timeout_seconds=args.jev_timeout_seconds,
        jev_baseline_path=args.jev_baseline,
        candidate_strategy=args.candidate_strategy,
        candidate_k=args.candidate_k,
        navigate=args.navigate,
        coverage=args.coverage,
        coverage_global_k=args.coverage_global_k,
        coverage_per_document=_parse_ks(args.coverage_per_document),
        coverage_v2=args.coverage_v2,
        coverage_v2_passes=args.coverage_v2_passes,
        coverage_v3=args.coverage_v3,
        coverage_budgets=_parse_budgets(args.coverage_budgets),
        expand_queries=args.expand_queries,
        profile_retrieval=args.profile_retrieval,
        decide_expansion=args.decide_expansion,
        compare_embeddings=args.compare_embeddings,
        analysis_cost=args.analysis_cost,
        evidence_curve=args.evidence_curve,
        workspace_stop_replay=args.workspace_stop_replay,
        proof_gap=args.proof_gap,
        proof_contract=args.proof_contract,
        proof_work=args.proof_work,
        proof_link=args.proof_link,
        proof_morph=args.proof_morph,
        proof_jev=args.proof_jev,
        proof_gate=args.proof_gate,
        proof_found=args.proof_found,
        proof_evidence=args.proof_evidence,
        proof_logic=args.proof_logic,
        proof_predicate=args.proof_predicate,
        proof_proposed=args.proof_proposed,
        blind_carveout=args.blind_carveout,
        coverage_query_variant=args.coverage_query_variant,
        coverage_gold_ids=tuple(args.coverage_gold_id),
        coverage_v3_baseline=args.coverage_v3_baseline,
        proof_rule=args.proof_rule,
        coverage_proof_gate=args.coverage_proof_gate,
        decision_trace=args.decision_trace,
        inspect_decision_trace=args.inspect_decision_trace,
        proof_requirements=args.proof_requirements,
        gold_map_v2=args.gold_map_v2,
        decision_contract=args.decision_contract,
        clause_resolve=args.clause_resolve,
        anaphor_resolve=args.anaphor_resolve,
        leftover_diagnosis=args.leftover_diagnosis,
        citation_labels=args.citation_labels,
        discovery_diagnosis=args.discovery_diagnosis,
        two_stage_retrieval=args.two_stage_retrieval,
        cerebras_rerank=args.cerebras_rerank,
        cerebras_api_key=args.cerebras_api_key,
        cerebras_base_url=args.cerebras_base_url,
        cerebras_model=args.cerebras_model,
        cerebras_k=args.cerebras_k,
        cerebras_output=args.cerebras_output,
        cerebras_qwen=args.cerebras_qwen,
        cerebras_reasoning=args.cerebras_reasoning,
        cerebras_k100=args.cerebras_k100,
        cerebras_split50=args.cerebras_split50,
        cerebras_second_opinion=args.cerebras_second_opinion,
        tabular_review=args.tabular_review,
        tabular_qwen=args.tabular_qwen,
        tabular_citation=args.tabular_citation,
        tabular_k10=args.tabular_k10,
        tabular_k10_errors=args.tabular_k10_errors,
        tabular_direct=args.tabular_direct,
        tabular_signals=args.tabular_signals,
        tabular_dense=args.tabular_dense,
        tabular_dense_errors=args.tabular_dense_errors,
        tabular_prompt_dev=args.tabular_prompt_dev,
        tabular_prompt_en=args.tabular_prompt_en,
        tabular_status_v2=args.tabular_status_v2,
        tabular_status_v2_repeats=args.tabular_status_v2_repeats,
        tabular_probability=args.tabular_probability,
        tabular_question_gold=args.tabular_question_gold,
        tabular_user_gold=args.tabular_user_gold,
        tabular_holdout=args.tabular_holdout,
        tabular_holdout_run=args.tabular_holdout_run,
        tabular_enrich=args.tabular_enrich,
        tabular_enrich_run=args.tabular_enrich_run,
        tabular_enrich_reject=args.tabular_enrich_reject,
        tabular_present=args.tabular_present,
        tabular_present_run=args.tabular_present_run,
        tabular_present_reject=args.tabular_present_reject,
        tabular_multi_run=args.tabular_multi_run,
        doctype_gold=args.doctype_gold,
        doctype_run=args.doctype_run,
        document_tags_gold=args.document_tags_gold,
        document_tags_run=args.document_tags_run,
        document_tags_lifecycle=args.document_tags_lifecycle,
        document_tags_close=args.document_tags_close,
        bm25_compare=args.bm25_compare,
        bm25_scope=args.bm25_scope,
        bm25_analyzer=args.bm25_analyzer,
        bm25_index_dir=args.bm25_index_dir,
        bm25_branch_depth=args.bm25_branch_depth,
        bm25_local_ks=_parse_ks(args.bm25_local_ks),
        bm25_paging=args.bm25_paging,
        bm25_page_size=args.bm25_page_size,
        bm25_answer_test=args.bm25_answer_test,
        bm25_candidates=args.bm25_candidates,
        bm25_repeats=args.bm25_repeats,
        bm25_gold_dir=args.bm25_gold_dir,
        bm25_question_gold=args.bm25_question_gold,
        bm25_rebuild_index=args.bm25_rebuild_index,
        discovery_test=args.discovery_test,
        document_properties=args.document_properties,
        property_track=args.property_track,
        property_taxonomy=args.property_taxonomy,
        property_gold_mapping=args.property_gold_mapping,
        property_bm25_run=args.property_bm25_run,
        jev_property_verification=args.jev_property_verification,
        jev_property_review=args.jev_property_review,
        jev_end_to_end=args.jev_end_to_end,
        jev_local_k=args.jev_local_k,
        jev_local_abc=args.jev_local_abc,
        jev_local_baseline=args.jev_local_baseline,
        jev_evidence_queries=args.jev_evidence_queries,
        jev_presentation=args.jev_presentation,
        jev_validation=args.jev_validation,
        freeze_baseline=args.freeze_baseline,
    )
    if config.generate_corpus is not None and not config.suite:
        if config.input_dir is None:
            print("--input is required with --generate-corpus", file=sys.stderr)
            return 2
        generate_corpus(config.input_dir, config.generate_corpus)
    if args.gold and not config.suite:
        return _run_gold(config)
    if config.classify_jev:
        return _run_jev(config)
    if config.navigate:
        return _run_navigation(config)
    if config.coverage:
        return _run_coverage(config)
    if config.coverage_v2:
        return _run_coverage_v2(config)
    if config.coverage_v3:
        return _run_coverage_v3(config)
    if config.expand_queries:
        return _run_expand_queries(config)
    if config.bm25_compare:
        return _run_bm25_compare(config)
    if config.discovery_test:
        return _run_discovery(config)
    if config.document_properties:
        return _run_document_properties(config)
    if config.jev_property_verification:
        return _run_jev_property_verification(config)
    if config.jev_end_to_end:
        return _run_jev_end_to_end(config)
    if config.jev_local_abc:
        return _run_jev_local_abc(config)
    if config.jev_presentation:
        return _run_jev_presentation(config)
    if config.jev_validation:
        return _run_jev_validation(config)
    if config.profile_retrieval:
        return _run_profile_retrieval(config)
    if config.decide_expansion:
        return _run_decide_expansion(config)
    if config.compare_embeddings:
        return _run_compare_embeddings(config)
    if config.analysis_cost:
        return _run_analysis_cost(config)
    if config.evidence_curve:
        return _run_evidence_curve(config)
    if config.workspace_stop_replay:
        return _run_workspace_stop_replay(config)
    if config.proof_gap:
        return _run_proof_gap(config)
    if config.proof_contract:
        return _run_proof_contract(config)
    if config.proof_work:
        return _run_proof_work(config)
    if config.proof_link:
        return _run_proof_link(config)
    if config.proof_morph:
        return _run_proof_morph(config)
    if config.proof_jev:
        return _run_proof_jev(config)
    if config.proof_gate:
        return _run_proof_gate(config)
    if config.proof_found:
        return _run_proof_found(config)
    if config.proof_evidence:
        return _run_proof_evidence(config)
    if config.proof_logic:
        return _run_proof_logic(config)
    if config.proof_predicate:
        return _run_proof_predicate(config)
    if config.proof_proposed:
        return _run_proof_proposed(config)
    if config.blind_carveout:
        return _run_blind_carveout(config)
    if config.inspect_decision_trace:
        return _run_decision_trace(config)
    if config.proof_requirements:
        return _run_proof_requirements(config)
    if config.gold_map_v2:
        return _run_gold_map(config)
    if config.decision_contract:
        return _run_decision_contract(config)
    if config.clause_resolve:
        return _run_clause_resolve(config)
    if config.anaphor_resolve:
        return _run_anaphor_resolve(config)
    if config.leftover_diagnosis:
        return _run_leftover_diagnosis(config)
    if config.citation_labels:
        return _run_citation_labels(config)
    if config.discovery_diagnosis:
        return _run_discovery_diagnosis(config)
    if config.two_stage_retrieval:
        return _run_two_stage_retrieval(config)
    if config.cerebras_rerank:
        return _run_cerebras_rerank(config)
    if config.cerebras_output:
        return _run_cerebras_output(config)
    if config.cerebras_qwen:
        return _run_cerebras_qwen(config)
    if config.cerebras_reasoning:
        return _run_cerebras_reasoning(config)
    if config.cerebras_k100:
        return _run_cerebras_k100(config)
    if config.cerebras_split50:
        return _run_cerebras_split50(config)
    if config.cerebras_second_opinion:
        return _run_cerebras_second_opinion(config)
    if config.tabular_review:
        return _run_tabular_review(config)
    if config.tabular_qwen:
        return _run_tabular_qwen(config)
    if config.tabular_citation:
        return _run_tabular_citation(config)
    if config.tabular_k10:
        return _run_tabular_k10(config)
    if config.tabular_k10_errors:
        return _run_tabular_k10_errors(config)
    if config.tabular_direct:
        return _run_tabular_direct(config)
    if config.tabular_signals:
        return _run_tabular_signals(config)
    if config.tabular_dense:
        return _run_tabular_dense(config)
    if config.tabular_dense_errors:
        return _run_tabular_dense_errors(config)
    if config.tabular_prompt_dev:
        return _run_tabular_prompt_dev(config)
    if config.tabular_prompt_en:
        return _run_tabular_prompt_en(config)
    if config.tabular_status_v2:
        return _run_tabular_status_v2(config)
    if config.tabular_status_v2_repeats:
        return _run_tabular_status_v2_repeats(config)
    if config.tabular_probability:
        return _run_tabular_probability(config)
    if config.tabular_question_gold:
        return _run_tabular_question_gold(config)
    if config.tabular_user_gold:
        return _run_tabular_user_gold(config)
    if config.tabular_holdout:
        return _run_tabular_holdout(config)
    if config.tabular_holdout_run:
        return _run_tabular_holdout_run(config)
    if config.tabular_enrich:
        return _run_tabular_enrich(config)
    if config.tabular_enrich_run:
        return _run_tabular_enrich_run(config)
    if config.tabular_enrich_reject:
        return _run_tabular_enrich_reject(config)
    if config.tabular_present:
        return _run_tabular_present(config)
    if config.tabular_present_run:
        return _run_tabular_present_run(config)
    if config.tabular_present_reject:
        return _run_tabular_present_reject(config)
    if config.tabular_multi_run:
        return _run_tabular_multi_run(config)
    if config.doctype_gold:
        return _run_doctype_gold(config)
    if config.doctype_run:
        return _run_doctype_run(config)
    if config.document_tags_gold:
        return _run_document_tags_gold(config)
    if config.document_tags_run:
        return _run_document_tags_run(config)
    if config.document_tags_lifecycle:
        return _run_document_tags_lifecycle(config)
    if config.document_tags_close:
        return _run_document_tags_close(config)
    if config.verify_only:
        errors = run_verify(config)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print("verification ok")
        return 0
    if config.suite:
        payload = run_suite(config)
        print(json.dumps(_suite_preview(payload), ensure_ascii=False, indent=2))
        return 0
    if config.retrieve_gold is not None and config.input_dir is None:
        return _run_retrieval(config)
    if config.graph_only:
        prepared = prepare_documents(config)
        report = write_prepared(config, prepared)
    else:
        report = run_ingest(config)
    payload = report_payload(config, report)
    if config.output_path is not None and config.retrieve_gold is None:
        write_report(config, report, config.output_path)
    if config.benchmark:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif config.retrieve_gold is None:
        print(
            f"ingested {payload['document_count']} files: "
            f"{payload['published']} published, {payload['failed']} failed "
            f"in {report.total_seconds:.2f}s"
        )
    if payload["failed"] != 0:
        return 1
    if config.retrieve_gold is not None:
        return _run_retrieval(config)
    return 0


COVERAGE_GOLD_DIR = Path(__file__).resolve().parents[1] / "retrieval_gold"


def _run_coverage_v2(config: IngestConfig) -> int:
    report = run_coverage_v2(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
        concurrency=config.jev_concurrency,
        global_k=config.coverage_global_k,
        max_passes=config.coverage_v2_passes,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_coverage_v2_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _coverage_v2_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        variants = {}
        for name, row in (item.get("variants") or {}).items():
            variants[name] = {
                "document_recall": row.get("document_recall"),
                "jev_yes_document_recall": row.get("jev_yes_document_recall"),
                "jev_calls": row.get("jev_calls"),
                "cache_hits": row.get("cache_hits"),
                "classified": row.get("classified"),
                "hop_fetches": row.get("hop_fetches"),
                "first_complete_phase": row.get("first_complete_phase"),
                "first_complete_classified": row.get("first_complete_classified"),
                "unresolved_documents": row.get("unresolved_documents"),
                "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
                "false_negative_documents": row.get("false_negative_documents"),
                "status_counts": row.get("status_counts"),
                "timeline": [
                    {
                        "phase": point.get("phase"),
                        "classified": point.get("classified"),
                        "jev_yes_document_recall": point.get("jev_yes_document_recall"),
                        "unresolved_relevant": point.get("unresolved_relevant"),
                    }
                    for point in (row.get("timeline") or [])
                ],
            }
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "proof_kind": item.get("proof_kind"),
                "variants": variants,
            }
        )
    return {
        "operation": payload.get("operation"),
        "controller": payload.get("controller"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "global_k": payload.get("global_k"),
        "max_passes": payload.get("max_passes"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_coverage_v3(config: IngestConfig) -> int:
    report = run_coverage_v3(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
        concurrency=config.jev_concurrency,
        global_k=config.coverage_global_k,
        budgets=config.coverage_budgets,
        query_variant=config.coverage_query_variant,
        gold_ids=config.coverage_gold_ids or None,
        proof_rule=config.proof_rule,
        proof_gate=config.coverage_proof_gate,
        decision_trace=config.decision_trace,
    )
    if config.coverage_v3_baseline is not None:
        frozen = json.loads(config.coverage_v3_baseline.read_text(encoding="utf-8"))
        for item in frozen.get("golds") or []:
            if item.get("gold_id") == "confidentiality" and item.get("recall_at_50") is None:
                item["recall_at_50"] = 0.46153846153846156
                item["document_coverage_at_50"] = 0.46153846153846156
        gold_id = (report.payload.get("golds") or [{}])[0].get("gold_id")
        if gold_id:
            report.payload["versus_baseline_v3"] = compare_v3_golds(
                frozen,
                report.payload,
                gold_id=str(gold_id),
            )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_coverage_v3_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _coverage_v3_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "proof_kind": item.get("proof_kind"),
                "query_variant": item.get("query_variant"),
                "query_used": item.get("query_used"),
                "recall_at_50": item.get("recall_at_50"),
                "document_coverage_at_50": item.get("document_coverage_at_50"),
                "matched_v2_at": item.get("matched_v2_at"),
                "budgets": [
                    {
                        "budget": row.get("budget"),
                        "document_recall": row.get("document_recall"),
                        "jev_yes_document_recall": row.get("jev_yes_document_recall"),
                        "jev_calls": row.get("jev_calls"),
                        "cache_hits": row.get("cache_hits"),
                        "classified": row.get("classified"),
                        "hop_fetches": row.get("hop_fetches"),
                        "first_complete_classified": row.get("first_complete_classified"),
                        "matched_v2_recall": row.get("matched_v2_recall"),
                        "unresolved_documents": row.get("unresolved_documents"),
                        "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
                        "false_negative_documents": row.get("false_negative_documents"),
                        "budget_exhausted_documents": row.get("budget_exhausted_documents"),
                        "budget_exhausted_relevant": row.get("budget_exhausted_relevant"),
                        "evidence_found_nonrelevant": row.get("evidence_found_nonrelevant"),
                        "gate_undecided": row.get("gate_undecided"),
                        "gate_blocked": row.get("gate_blocked"),
                        "status_counts": row.get("status_counts"),
                        "composite_groups": row.get("composite_groups"),
                    }
                    for row in (item.get("budgets") or [])
                ],
            }
        )
    return {
        "operation": payload.get("operation"),
        "controller": payload.get("controller"),
        "proof_rule": payload.get("proof_rule"),
        "proof_gate": payload.get("proof_gate"),
        "does_not_replace_coverage_v3": payload.get("does_not_replace_coverage_v3"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "query_variant": payload.get("query_variant"),
        "default_retriever_unchanged": payload.get("default_retriever_unchanged"),
        "budget_exhausted_is_not_absent": payload.get("budget_exhausted_is_not_absent"),
        "global_k": payload.get("global_k"),
        "budgets": payload.get("budgets"),
        "wall_seconds": payload.get("wall_seconds"),
        "versus_baseline_v3": payload.get("versus_baseline_v3"),
        "golds": golds,
    }


def _run_proof_evidence(config: IngestConfig) -> int:
    payload = run_proof_evidence()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_evidence_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_evidence_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "no_new_jev": payload.get("no_new_jev"),
        "no_new_controller": payload.get("no_new_controller"),
        "claim": payload.get("claim"),
        "all_positives_found": payload.get("all_positives_found"),
        "false_found": payload.get("false_found"),
        "zero_false_complete": payload.get("zero_false_complete"),
        "fabricated_span_rejected": payload.get("fabricated_span_rejected"),
        "heading_alone_is_not_proof": payload.get("heading_alone_is_not_proof"),
        "undecided_kept": payload.get("undecided_kept"),
        "avtal_12": payload.get("avtal_12"),
        "avtal_49": payload.get("avtal_49"),
        "avtal_46_split": payload.get("avtal_46_split"),
        "avtal_60_with_irrelevant_hop": payload.get("avtal_60_with_irrelevant_hop"),
    }


def _run_proof_logic(config: IngestConfig) -> int:
    payload = run_proof_logic()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_logic_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_logic_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_evidence_contract": payload.get("does_not_change_evidence_contract"),
        "not_a_gate": payload.get("not_a_gate"),
        "not_a_parser": payload.get("not_a_parser"),
        "schema": payload.get("schema"),
        "all_positives_claim_form": payload.get("all_positives_claim_form"),
        "pairs_match": payload.get("pairs_match"),
        "avtal_60_claim_form": payload.get("avtal_60_claim_form"),
        "avtal_60_not_inverted": payload.get("avtal_60_not_inverted"),
        "quote_and_yes_is_not_proof": payload.get("quote_and_yes_is_not_proof"),
        "logic_synonym_claim_count": payload.get("logic_synonym_claim_count"),
        "jev_synonym_recall": payload.get("jev_synonym_recall"),
        "avtal_60": payload.get("avtal_60"),
        "inverted_quote_and_yes": payload.get("inverted_quote_and_yes"),
    }


def _run_proof_predicate(config: IngestConfig) -> int:
    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --proof-predicate", file=sys.stderr)
        return 2
    payload = run_proof_predicate(
        client=HttpJevClient(
            api_key=config.typesafe_api_key,
            base_url=config.typesafe_base_url,
        ),
        model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
        concurrency=config.jev_concurrency,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_predicate_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_predicate_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_evidence_contract": payload.get("does_not_change_evidence_contract"),
        "not_a_supported_classifier": payload.get("not_a_supported_classifier"),
        "proposed_is_not_evidence_found": payload.get("proposed_is_not_evidence_found"),
        "paraphrase_operator_recall": payload.get("paraphrase_operator_recall"),
        "inverted_operator": payload.get("inverted_operator"),
        "inverted_not_found": payload.get("inverted_not_found"),
        "avtal_60_picks_carveout_sentence": payload.get("avtal_60_picks_carveout_sentence"),
        "avtal_60_not_indirect_damage": payload.get("avtal_60_not_indirect_damage"),
        "avtal_60_found": payload.get("avtal_60_found"),
        "cooccurrence_none": payload.get("cooccurrence_none"),
        "wrong_clause_none": payload.get("wrong_clause_none"),
        "zero_false_complete": payload.get("zero_false_complete"),
        "verified_count": payload.get("verified_count"),
        "proposed_count": payload.get("proposed_count"),
        "insufficient_count": payload.get("insufficient_count"),
        "false_found": payload.get("false_found"),
        "jev_model": payload.get("jev_model"),
    }


def _run_proof_proposed(config: IngestConfig) -> int:
    payload = run_proof_proposed()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_proposed_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_proposed_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_jev": payload.get("no_new_jev"),
        "no_looser_verified_rule": payload.get("no_looser_verified_rule"),
        "proposed_count": payload.get("proposed_count"),
        "more_information_can_verify_count": payload.get("more_information_can_verify_count"),
        "semantic_paraphrase_count": payload.get("semantic_paraphrase_count"),
        "other_relation_count": payload.get("other_relation_count"),
        "missing_relation_in_span_count": payload.get("missing_relation_in_span_count"),
        "incomplete_reference_count": payload.get("incomplete_reference_count"),
        "ambiguous_count": payload.get("ambiguous_count"),
        "causes": payload.get("causes"),
    }


def _run_blind_carveout(config: IngestConfig) -> int:
    payload = run_blind_carveout()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_blind_carveout_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _blind_carveout_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "gold_is_synthetic": payload.get("gold_is_synthetic"),
        "yes_count": payload.get("yes_count"),
        "yes_link": payload.get("yes_link"),
        "yes_claim_form": payload.get("yes_claim_form"),
        "no_link": payload.get("no_link"),
        "uncertain_link": payload.get("uncertain_link"),
        "yes_multi_clause": payload.get("yes_multi_clause"),
        "no_traps": payload.get("no_traps"),
        "error_layers": payload.get("error_layers"),
    }


def _run_decision_trace(config: IngestConfig) -> int:
    payload = run_decision_trace()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_decision_trace_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_proof_requirements(config: IngestConfig) -> int:
    payload = run_proof_requirements()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_requirements_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_requirements_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "answer_contract": payload.get("answer_contract"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "no_new_proof_engine": payload.get("no_new_proof_engine"),
        "accounting": payload.get("accounting"),
        "requirements": payload.get("requirements"),
        "rejected_fixes": payload.get("rejected_fixes"),
        "unmapped_gold_quote": payload.get("unmapped_gold_quote"),
    }


def _run_gold_map(config: IngestConfig) -> int:
    payload = run_gold_map(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_gold_map_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_decision_contract(config: IngestConfig) -> int:
    payload = run_decision_contract()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_decision_contract_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_clause_resolve(config: IngestConfig) -> int:
    payload = run_clause_resolve(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_clause_resolve_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_anaphor_resolve(config: IngestConfig) -> int:
    payload = run_anaphor_resolve(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_anaphor_resolve_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_leftover_diagnosis(config: IngestConfig) -> int:
    payload = run_leftover_diagnosis(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_leftover_diagnosis_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_citation_labels(config: IngestConfig) -> int:
    payload = run_citation_labels(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_citation_labels_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_discovery_diagnosis(config: IngestConfig) -> int:
    payload = run_discovery_diagnosis(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        dense_model=config.dense_model,
        openai_base_url=config.openai_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_discovery_diagnosis_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_two_stage_retrieval(config: IngestConfig) -> int:
    payload = run_two_stage_retrieval(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        dense_model=config.dense_model,
        openai_base_url=config.openai_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_two_stage_retrieval_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_rerank(config: IngestConfig) -> int:
    payload = run_cerebras_rerank(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        k=config.cerebras_k,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
        cerebras_model=config.cerebras_model,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_rerank_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_output(config: IngestConfig) -> int:
    payload = run_cerebras_output(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
        cerebras_model=config.cerebras_model,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_output_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_qwen(config: IngestConfig) -> int:
    payload = run_cerebras_qwen(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_qwen_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_reasoning(config: IngestConfig) -> int:
    payload = run_cerebras_reasoning(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_reasoning_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_probability(config: IngestConfig) -> int:
    payload = run_tabular_probability(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_probability_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_question_gold(config: IngestConfig) -> int:
    payload = review_question_gold()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_question_gold_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_user_gold(config: IngestConfig) -> int:
    payload = compare_user_gold()
    write_user_gold_table(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_user_gold_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_holdout(config: IngestConfig) -> int:
    payload = review_holdout_gold()
    write_holdout_gold_table(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_holdout_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_holdout_run(config: IngestConfig) -> int:
    payload = run_tabular_holdout(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    write_holdout_run_table(payload)
    if config.freeze_baseline:
        write_holdout_run_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_holdout_run_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_enrich(config: IngestConfig) -> int:
    payload = review_enrich_protocol()
    write_enrich_protocol_table(payload)
    if config.freeze_baseline:
        write_enrich_protocol_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_enrich_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_enrich_run(config: IngestConfig) -> int:
    payload = run_tabular_enrich(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
    )
    write_enrich_run_table(payload)
    if config.freeze_baseline:
        write_enrich_run_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_enrich_run_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_enrich_reject(config: IngestConfig) -> int:
    payload = review_enrich_reject()
    write_enrich_reject_table(payload)
    if config.freeze_baseline:
        write_enrich_reject_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_enrich_reject_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_present(config: IngestConfig) -> int:
    payload = review_present_protocol()
    write_present_protocol_table(payload)
    if config.freeze_baseline:
        write_present_protocol_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_present_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_present_run(config: IngestConfig) -> int:
    payload = run_tabular_present(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    write_present_run_table(payload)
    if config.freeze_baseline:
        write_present_run_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_present_run_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_present_reject(config: IngestConfig) -> int:
    payload = review_present_reject()
    write_present_reject_table(payload)
    if config.freeze_baseline:
        write_present_reject_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_present_reject_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_multi_run(config: IngestConfig) -> int:
    payload = run_tabular_multi(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    write_multi_run_table(payload)
    if config.freeze_baseline:
        write_multi_run_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_multi_run_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_doctype_gold(config: IngestConfig) -> int:
    payload = review_doctype_gold()
    write_doctype_gold_table(payload)
    if config.freeze_baseline:
        write_doctype_gold_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_doctype_gold_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_doctype_run(config: IngestConfig) -> int:
    payload = run_doctype(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    write_doctype_run_table(payload)
    if config.freeze_baseline:
        write_doctype_run_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_doctype_run_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_document_tags_gold(config: IngestConfig) -> int:
    payload = review_document_tags_gold()
    write_document_tags_gold_table(payload)
    if config.freeze_baseline:
        write_document_tags_gold_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_document_tags_gold_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_document_tags_run(config: IngestConfig) -> int:
    payload = run_document_tags(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    write_document_tags_run_table(payload)
    if config.freeze_baseline:
        write_document_tags_run_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_document_tags_run_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_document_tags_lifecycle(config: IngestConfig) -> int:
    payload = run_document_tags_lifecycle()
    write_document_tags_lifecycle_table(payload)
    if config.freeze_baseline:
        write_document_tags_lifecycle_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_document_tags_lifecycle_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_document_tags_close(config: IngestConfig) -> int:
    payload = review_document_tags_close()
    write_document_tags_close_table(payload)
    if config.freeze_baseline:
        write_document_tags_close_baseline(payload)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_document_tags_close_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_status_v2_repeats(config: IngestConfig) -> int:
    payload = run_tabular_status_v2_repeats(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_status_v2_repeats_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_status_v2(config: IngestConfig) -> int:
    payload = run_tabular_status_v2(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_status_v2_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_prompt_en(config: IngestConfig) -> int:
    payload = run_tabular_prompt_en(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_prompt_en_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_prompt_dev(config: IngestConfig) -> int:
    payload = run_tabular_prompt_dev(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_prompt_dev_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_dense_errors(config: IngestConfig) -> int:
    payload = run_tabular_dense_errors()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_dense_errors_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_dense(config: IngestConfig) -> int:
    payload = run_tabular_dense(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_dense_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_signals(config: IngestConfig) -> int:
    payload = run_tabular_signals(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_signals_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_direct(config: IngestConfig) -> int:
    payload = run_tabular_direct(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_direct_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_k10_errors(config: IngestConfig) -> int:
    payload = run_tabular_k10_errors()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_k10_errors_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_k10(config: IngestConfig) -> int:
    payload = run_tabular_k10(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_k10_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_citation(config: IngestConfig) -> int:
    payload = run_tabular_citation()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_citation_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_qwen(config: IngestConfig) -> int:
    payload = run_tabular_qwen(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_qwen_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_tabular_review(config: IngestConfig) -> int:
    payload = run_tabular_review(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        jev_timeout_seconds=config.jev_timeout_seconds,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
        cerebras_model=config.cerebras_model,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(_tabular_review_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_second_opinion(config: IngestConfig) -> int:
    payload = run_cerebras_second_opinion(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_second_opinion_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_split50(config: IngestConfig) -> int:
    payload = run_cerebras_split50(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_split50_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _run_cerebras_k100(config: IngestConfig) -> int:
    payload = run_cerebras_k100(
        db_path=config.db_path,
        gold_dir=config.gold_dir,
        dense_dimension=config.dense_dimension or 3072,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        dense_model=config.dense_model,
        cerebras_api_key=config.cerebras_api_key,
        cerebras_base_url=config.cerebras_base_url,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_cerebras_k100_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _citation_labels_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "does_not_change_relation_test": payload.get("does_not_change_relation_test"),
        "reference_counts": (payload.get("reference") or {}).get("counts"),
        "treatment_counts": (payload.get("treatment") or {}).get("counts"),
        "delta": payload.get("delta"),
        "ability_curve": payload.get("ability_curve"),
        "cases": payload.get("cases"),
    }


def _leftover_diagnosis_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_jev": payload.get("no_new_jev"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "does_not_start_next_ability": payload.get("does_not_start_next_ability"),
        "quality_reference": payload.get("quality_reference"),
        "summary": payload.get("summary"),
    }


def _discovery_diagnosis_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_jev": payload.get("no_new_jev"),
        "no_new_controller": payload.get("no_new_controller"),
        "does_not_change_retrieval": payload.get("does_not_change_retrieval"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "ranking_computed": payload.get("ranking_computed"),
        "quality_reference": payload.get("quality_reference"),
        "summary": payload.get("summary"),
        "rows": payload.get("rows"),
    }


def _two_stage_retrieval_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_jev": payload.get("no_new_jev"),
        "no_new_controller": payload.get("no_new_controller"),
        "does_not_change_proof": payload.get("does_not_change_proof"),
        "improvement_is_budget_allocation": payload.get("improvement_is_budget_allocation"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "quality_reference": payload.get("quality_reference"),
        "stage1_document_discovery": payload.get("stage1_document_discovery"),
        "strategies": payload.get("strategies"),
        "rows": payload.get("rows"),
    }


def _cerebras_rerank_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "task": payload.get("task"),
        "no_coverage_controller": payload.get("no_coverage_controller"),
        "no_proof_evaluator": payload.get("no_proof_evaluator"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "k": payload.get("k"),
        "model": payload.get("model"),
        "summary": payload.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "precision": row.get("precision"),
                "candidate_recall": row.get("candidate_recall"),
                "corpus_recall": row.get("corpus_recall"),
                "corpus_document_recall": row.get("corpus_document_recall"),
                "match": row.get("match"),
                "uncertain": row.get("uncertain"),
                "ttft_seconds": row.get("ttft_seconds"),
                "model_seconds": row.get("model_seconds"),
            }
            for row in payload.get("golds") or []
        ],
        "wall_seconds": payload.get("wall_seconds"),
    }


def _cerebras_output_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "same_frozen_top50": payload.get("same_frozen_top50"),
        "no_new_retrieval": payload.get("no_new_retrieval"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "summary": payload.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "precision": row.get("precision"),
                "candidate_recall": row.get("candidate_recall"),
                "id_errors": row.get("id_errors"),
                "completion_tokens": row.get("completion_tokens"),
                "ttft_seconds": row.get("ttft_seconds"),
                "model_seconds": row.get("model_seconds"),
                "delta": row.get("delta"),
            }
            for row in payload.get("golds") or []
        ],
        "wall_seconds": payload.get("wall_seconds"),
    }


def _cerebras_qwen_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "model": payload.get("model"),
        "reference_model": payload.get("reference_model"),
        "same_frozen_top50": payload.get("same_frozen_top50"),
        "same_minimal_json": payload.get("same_minimal_json"),
        "no_new_retrieval": payload.get("no_new_retrieval"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "summary": payload.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "precision": row.get("precision"),
                "candidate_recall": row.get("candidate_recall"),
                "id_errors": row.get("id_errors"),
                "prompt_tokens": row.get("prompt_tokens"),
                "completion_tokens": row.get("completion_tokens"),
                "reasoning_tokens": row.get("reasoning_tokens"),
                "cost_usd": row.get("cost_usd"),
                "ttft_seconds": row.get("ttft_seconds"),
                "model_seconds": row.get("model_seconds"),
                "delta": row.get("delta"),
            }
            for row in payload.get("golds") or []
        ],
        "wall_seconds": payload.get("wall_seconds"),
    }


def _cerebras_reasoning_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "model": payload.get("model"),
        "reasoning_off_supported": payload.get("reasoning_off_supported"),
        "lowest_supported": payload.get("lowest_supported"),
        "current_was_not_rerun": payload.get("current_was_not_rerun"),
        "same_frozen_top50": payload.get("same_frozen_top50"),
        "does_not_replace_cerebras_output": payload.get("does_not_replace_cerebras_output"),
        "summary": payload.get("summary"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_status_v2_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "nearby_is_uncertain": payload.get("nearby_is_uncertain"),
        "default_prompt_unchanged": payload.get("default_prompt_unchanged"),
        "headline": payload.get("headline"),
        "acceptance": payload.get("acceptance"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_probability_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "p2_implemented": payload.get("p2_implemented"),
        "score_type": payload.get("score_type"),
        "default_prompt_unchanged": payload.get("default_prompt_unchanged"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_question_gold_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_gold": payload.get("does_not_change_gold"),
        "do_not_retune_gold_to_model": payload.get("do_not_retune_gold_to_model"),
        "user_question_is_the_contract": payload.get("user_question_is_the_contract"),
        "headline": payload.get("headline"),
    }


def _tabular_user_gold_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "does_not_change_retrieval_gold": payload.get("does_not_change_retrieval_gold"),
        "user_question_is_the_contract": payload.get("user_question_is_the_contract"),
        "headline": payload.get("headline"),
        "historical_passage_gold": payload.get("historical_passage_gold"),
    }


def _tabular_status_v2_repeats_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "jev_has_temperature_parameter": payload.get("jev_has_temperature_parameter"),
        "unused_hard_neg_are_in_distribution": payload.get(
            "unused_hard_neg_are_in_distribution"
        ),
        "default_prompt_unchanged": payload.get("default_prompt_unchanged"),
        "does_not_overwrite_status_v2": payload.get("does_not_overwrite_status_v2"),
        "headline": payload.get("headline"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_prompt_en_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "prior_instructions_were_already_english": payload.get(
            "prior_instructions_were_already_english"
        ),
        "default_question_language_unchanged": payload.get(
            "default_question_language_unchanged"
        ),
        "picked": payload.get("picked"),
        "headline": payload.get("headline"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_prompt_dev_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "known_errors_are_not_selection_gold": payload.get(
            "known_errors_are_not_selection_gold"
        ),
        "default_prompt_unchanged": payload.get("default_prompt_unchanged"),
        "picked": payload.get("picked"),
        "headline": payload.get("headline"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_holdout_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "models_not_run": payload.get("models_not_run"),
        "default_remains_d": payload.get("default_remains_d"),
        "e_is_next_candidate": payload.get("e_is_next_candidate"),
        "headline": payload.get("headline"),
    }


def _tabular_holdout_run_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_ingest": payload.get("does_not_change_ingest"),
        "does_not_run_cerebras": payload.get("does_not_run_cerebras"),
        "default_remains_d": payload.get("default_remains_d"),
        "e_is_next_candidate": payload.get("e_is_next_candidate"),
        "one_jev_call": payload.get("one_jev_call"),
        "no_structural_preprocess": payload.get("no_structural_preprocess"),
        "jev_calls": payload.get("jev_calls"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
    }


def _tabular_enrich_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "search_is_not_evidence": payload.get("search_is_not_evidence"),
        "hypothesis_2_not_built": payload.get("hypothesis_2_not_built"),
        "first_run": payload.get("first_run"),
        "reserved_documents": payload.get("reserved_documents"),
        "headline": payload.get("headline"),
    }


def _tabular_enrich_run_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "search_is_not_evidence": payload.get("search_is_not_evidence"),
        "does_not_write_overgraph": payload.get("does_not_write_overgraph"),
        "default_remains_d": payload.get("default_remains_d"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "prompt_tokens": payload.get("prompt_tokens"),
    }


def _tabular_enrich_reject_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "verdict": payload.get("verdict"),
        "rejected": payload.get("rejected"),
        "kept": payload.get("kept"),
        "does_not_run_c": payload.get("does_not_run_c"),
        "original_embeddings_stay": payload.get("original_embeddings_stay"),
        "next_is_candidate_presentation": payload.get("next_is_candidate_presentation"),
        "headline": payload.get("headline"),
    }


def _tabular_present_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "does_not_change_retrieval": payload.get("does_not_change_retrieval"),
        "same_five_units": payload.get("same_five_units"),
        "models_not_run": payload.get("models_not_run"),
        "default_remains_d": payload.get("default_remains_d"),
        "headline": payload.get("headline"),
    }


def _tabular_present_run_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_retrieval": payload.get("does_not_change_retrieval"),
        "same_five_units": payload.get("same_five_units"),
        "reserved_unused": payload.get("reserved_unused"),
        "default_remains_d": payload.get("default_remains_d"),
        "jev_calls": payload.get("jev_calls"),
        "heading_cited": payload.get("heading_cited"),
        "headline": payload.get("headline"),
        "paired": {
            key: (payload.get("paired") or {}).get(key)
            for key in (
                "changed",
                "lost_positive",
                "new_false_positive",
                "fixed_false_positive",
            )
        },
        "decision": payload.get("decision"),
    }


def _tabular_present_reject_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "verdict": payload.get("verdict"),
        "rejected": payload.get("rejected"),
        "kept": payload.get("kept"),
        "pause_micro_optimization": payload.get("pause_micro_optimization"),
        "next_quality_needs_new_capability": payload.get(
            "next_quality_needs_new_capability"
        ),
        "do_not_start_hypothesis_2_because_cheaper_failed": payload.get(
            "do_not_start_hypothesis_2_because_cheaper_failed"
        ),
        "does_not_run_reserved_holdout": payload.get("does_not_run_reserved_holdout"),
        "default_remains_d": payload.get("default_remains_d"),
        "e_is_strongest_measured_candidate": payload.get(
            "e_is_strongest_measured_candidate"
        ),
        "headline": payload.get("headline"),
    }


def _tabular_multi_run_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_retrieval": payload.get("does_not_change_retrieval"),
        "same_five_units": payload.get("same_five_units"),
        "one_jev_call": payload.get("one_jev_call"),
        "does_not_run_reserved_holdout": payload.get("does_not_run_reserved_holdout"),
        "default_remains_d": payload.get("default_remains_d"),
        "do_not_start_product_from_this_run": payload.get(
            "do_not_start_product_from_this_run"
        ),
        "jev_calls": payload.get("jev_calls"),
        "headline": payload.get("headline"),
        "paired": {
            key: (payload.get("paired") or {}).get(key)
            for key in ("changed", "more_gold", "more_extras")
        },
        "decision": payload.get("decision"),
    }


def _doctype_gold_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "models_not_run": payload.get("models_not_run"),
        "does_not_change_text_units": payload.get("does_not_change_text_units"),
        "does_not_change_answer_cell": payload.get("does_not_change_answer_cell"),
        "default_remains_d": payload.get("default_remains_d"),
        "principal_function_not_clauses": payload.get("principal_function_not_clauses"),
        "headline": payload.get("headline"),
    }


def _doctype_run_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_change_text_units": payload.get("does_not_change_text_units"),
        "does_not_change_answer_cell": payload.get("does_not_change_answer_cell"),
        "does_not_change_retrieval": payload.get("does_not_change_retrieval"),
        "default_remains_d": payload.get("default_remains_d"),
        "no_production_integration": payload.get("no_production_integration"),
        "jev_calls": payload.get("jev_calls"),
        "headline": {
            name: {
                "accuracy": (payload.get("headline") or {}).get(name, {}).get("accuracy"),
                "correct": (payload.get("headline") or {}).get(name, {}).get("correct"),
                "n": (payload.get("headline") or {}).get(name, {}).get("n"),
            }
            for name in ("A", "B", "C")
            if name in (payload.get("headline") or {})
        },
        "store": {
            key: (payload.get("store") or {}).get(key)
            for key in ("text_units_unchanged", "filter_seconds")
        },
        "decision": payload.get("decision"),
        "cost": payload.get("cost"),
    }


def _document_tags_gold_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "models_not_run": payload.get("models_not_run"),
        "does_not_change_text_units": payload.get("does_not_change_text_units"),
        "does_not_change_answer_cell": payload.get("does_not_change_answer_cell"),
        "does_not_change_doctype_baseline": payload.get("does_not_change_doctype_baseline"),
        "default_remains_d": payload.get("default_remains_d"),
        "headline": payload.get("headline"),
        "inventory": payload.get("inventory"),
    }


def _document_tags_run_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "reuses_frozen_doctype_b": payload.get("reuses_frozen_doctype_b"),
        "does_not_rerun_doctype_jev": payload.get("does_not_rerun_doctype_jev"),
        "does_not_change_text_units": payload.get("does_not_change_text_units"),
        "does_not_change_answer_cell": payload.get("does_not_change_answer_cell"),
        "does_not_change_doctype_baseline": payload.get("does_not_change_doctype_baseline"),
        "no_production_integration": payload.get("no_production_integration"),
        "jev_calls": payload.get("jev_calls"),
        "headline": {
            name: {
                "precision": (payload.get("headline") or {}).get(name, {}).get("precision"),
                "recall": (payload.get("headline") or {}).get(name, {}).get("recall"),
                "hits": (payload.get("headline") or {}).get(name, {}).get("hits"),
            }
            for name in ("A", "B")
            if name in (payload.get("headline") or {})
        },
        "store": {
            key: (payload.get("store") or {}).get(key)
            for key in (
                "text_units_unchanged",
                "filter_seconds",
                "type_correction_survives_reclassify",
                "rejected_tag_stays_rejected",
                "tenant_isolation",
            )
        },
        "decision": payload.get("decision"),
        "cost": payload.get("cost"),
    }


def _document_tags_lifecycle_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "models_not_run": payload.get("models_not_run"),
        "does_not_change_document_tags_run": payload.get("does_not_change_document_tags_run"),
        "a_is_cheap_ingest_candidate": payload.get("a_is_cheap_ingest_candidate"),
        "b_is_experimental_semantic_alternative": payload.get("b_is_experimental_semantic_alternative"),
        "automatic_tags_are_proposals": payload.get("automatic_tags_are_proposals"),
        "headline": payload.get("headline"),
        "proof": payload.get("proof"),
    }


def _document_tags_close_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_run_jev": payload.get("does_not_run_jev"),
        "experiment_closed": payload.get("experiment_closed"),
        "do_not_run_more_jev_on_16_docs": payload.get("do_not_run_more_jev_on_16_docs"),
        "a_is_cheap_ingest_candidate": payload.get("a_is_cheap_ingest_candidate"),
        "carry_to_socialism": payload.get("carry_to_socialism"),
        "headline": payload.get("headline"),
    }


def _tabular_dense_errors_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_model": payload.get("no_new_model"),
        "no_prompt_change": payload.get("no_prompt_change"),
        "default_hybrid_unchanged": payload.get("default_hybrid_unchanged"),
        "transitions": payload.get("transitions"),
        "headline": payload.get("headline"),
        "rows": len(payload.get("rows") or []),
        "avtal_13": payload.get("avtal_13"),
    }


def _tabular_dense_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "performance_reference": payload.get("performance_reference"),
        "retrieval_treatment": payload.get("retrieval_treatment"),
        "same_100_cells": payload.get("same_100_cells"),
        "no_new_model": payload.get("no_new_model"),
        "no_navigation": payload.get("no_navigation"),
        "default_hybrid_unchanged": payload.get("default_hybrid_unchanged"),
        "does_not_replace_tabular_direct": payload.get("does_not_replace_tabular_direct"),
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "recovered": {
            key: (payload.get("recovered") or {}).get(key)
            for key in (
                "confidentiality_misses",
                "recovered_cells",
                "recovered_citations",
                "still_failed",
                "new_gold_negative_false_answers",
                "cell_improvements",
                "cell_regressions",
            )
        },
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_signals_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "retrieval_baseline": payload.get("retrieval_baseline"),
        "same_100_cells": payload.get("same_100_cells"),
        "no_new_algorithm": payload.get("no_new_algorithm"),
        "no_answer_cell": payload.get("no_answer_cell"),
        "answer_cell_warranted": payload.get("answer_cell_warranted"),
        "hybrid_matches_frozen": payload.get("hybrid_matches_frozen"),
        "does_not_replace_tabular_direct": payload.get("does_not_replace_tabular_direct"),
        "headline": payload.get("headline"),
    }


def _tabular_direct_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "quality_reference": payload.get("quality_reference"),
        "hypothesis": payload.get("hypothesis"),
        "same_100_cells": payload.get("same_100_cells"),
        "same_five_candidates": payload.get("same_five_candidates"),
        "classify_skipped": payload.get("classify_skipped"),
        "judgments_passed_to_answer": payload.get("judgments_passed_to_answer"),
        "no_new_model": payload.get("no_new_model"),
        "no_navigation": payload.get("no_navigation"),
        "no_new_retrieval": payload.get("no_new_retrieval"),
        "default_k_unchanged": payload.get("default_k_unchanged"),
        "does_not_replace_tabular_v1": payload.get("does_not_replace_tabular_v1"),
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_k10_errors_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_model": payload.get("no_new_model"),
        "classify_gates_b_answer": payload.get("classify_gates_b_answer"),
        "answer_sees": payload.get("answer_sees"),
        "headline": payload.get("headline"),
        "rows": len(payload.get("rows") or []),
    }


def _tabular_k10_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "quality_reference": payload.get("quality_reference"),
        "k": payload.get("k"),
        "reference_k": payload.get("reference_k"),
        "same_100_cells": payload.get("same_100_cells"),
        "no_new_model": payload.get("no_new_model"),
        "no_navigation": payload.get("no_navigation"),
        "default_k_unchanged": payload.get("default_k_unchanged"),
        "does_not_replace_tabular_v1": payload.get("does_not_replace_tabular_v1"),
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "recovered": {
            key: (payload.get("recovered") or {}).get(key)
            for key in (
                "missing_gold_at_k5",
                "recoverable_at_k10",
                "present_at_k10",
                "recovered_cells",
                "still_missing_at_k10",
                "new_gold_negative_false_answers",
                "cell_improvements",
                "cell_regressions",
            )
        },
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_citation_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "quality_reference": payload.get("quality_reference"),
        "model_comparisons_paused": payload.get("model_comparisons_paused"),
        "no_new_model": payload.get("no_new_model"),
        "no_new_retrieval": payload.get("no_new_retrieval"),
        "does_not_replace_tabular_v1": payload.get("does_not_replace_tabular_v1"),
        "verdict": payload.get("verdict"),
        "next": payload.get("next"),
        "headline": payload.get("headline"),
    }


def _tabular_qwen_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "model": payload.get("model"),
        "reasoning_effort": payload.get("reasoning_effort"),
        "same_100_cells": payload.get("same_100_cells"),
        "no_new_retrieval": payload.get("no_new_retrieval"),
        "does_not_replace_tabular_v1": payload.get("does_not_replace_tabular_v1"),
        "cells": len(payload.get("cells") or []),
        "headline": payload.get("headline"),
        "versus": payload.get("versus"),
        "cost": payload.get("cost"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _tabular_review_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "synchronous": payload.get("synchronous"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "does_not_replace_coverage_v3": payload.get("does_not_replace_coverage_v3"),
        "selection_is_diagnostic": payload.get("selection_is_diagnostic"),
        "k": payload.get("k"),
        "cells": len(payload.get("cells") or []),
        "headline": payload.get("headline"),
        "cost": payload.get("cost"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _cerebras_second_opinion_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "no_new_jev": payload.get("no_new_jev"),
        "no_new_cerebras": payload.get("no_new_cerebras"),
        "no_router": payload.get("no_router"),
        "k200_not_started": payload.get("k200_not_started"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "summary": payload.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "overlap": row.get("overlap"),
                "jev_errors": row.get("jev_errors"),
                "corrected": row.get("corrected"),
                "worsened": row.get("worsened"),
                "same_error": row.get("same_error"),
                "jev_uncertain": row.get("jev_uncertain"),
                "uncertain_resolved_correct": row.get("uncertain_resolved_correct"),
                "uncertain_resolved_wrong": row.get("uncertain_resolved_wrong"),
                "jev_rescored": row.get("jev_rescored"),
                "cerebras_rescored": row.get("cerebras_rescored"),
            }
            for row in payload.get("golds") or []
        ],
    }


def _cerebras_split50_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "k": payload.get("k"),
        "batch_size": payload.get("batch_size"),
        "calls_per_question": payload.get("calls_per_question"),
        "setting": payload.get("setting"),
        "max_completion_tokens": payload.get("max_completion_tokens"),
        "one_shot_k100_not_retried": payload.get("one_shot_k100_not_retried"),
        "k200_not_started": payload.get("k200_not_started"),
        "second_opinion_not_started": payload.get("second_opinion_not_started"),
        "model_completes": payload.get("model_completes"),
        "does_not_replace_cerebras_output": payload.get("does_not_replace_cerebras_output"),
        "summary": payload.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "precision": row.get("precision"),
                "candidate_recall": row.get("candidate_recall"),
                "corpus_recall": row.get("corpus_recall"),
                "true_matches": row.get("true_matches"),
                "group_effects": row.get("group_effects"),
                "batch_quality": row.get("batch_quality"),
                "cost_usd": row.get("cost_usd"),
                "completion_tokens": row.get("completion_tokens"),
                "model_seconds": row.get("model_seconds"),
                "delta": row.get("delta"),
            }
            for row in payload.get("golds") or []
        ],
        "wall_seconds": payload.get("wall_seconds"),
    }


def _cerebras_k100_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "k": payload.get("k"),
        "setting": payload.get("setting"),
        "same_retrieval_strategy": payload.get("same_retrieval_strategy"),
        "k200_not_started": payload.get("k200_not_started"),
        "second_opinion_not_started": payload.get("second_opinion_not_started"),
        "model_completes": payload.get("model_completes"),
        "model_failure": payload.get("model_failure"),
        "does_not_replace_cerebras_output": payload.get("does_not_replace_cerebras_output"),
        "summary": payload.get("summary"),
        "golds": [
            {
                "gold_id": row.get("gold_id"),
                "precision": row.get("precision"),
                "candidate_recall": row.get("candidate_recall"),
                "corpus_recall": row.get("corpus_recall"),
                "true_matches": row.get("true_matches"),
                "effects": row.get("effects"),
                "cost_usd": row.get("cost_usd"),
                "cost_per_true_match_usd": row.get("cost_per_true_match_usd"),
                "completion_tokens": row.get("completion_tokens"),
                "model_seconds": row.get("model_seconds"),
                "delta": row.get("delta"),
            }
            for row in payload.get("golds") or []
        ],
        "wall_seconds": payload.get("wall_seconds"),
    }


def _anaphor_resolve_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "same_mapping_for_both_variants": payload.get("same_mapping_for_both_variants"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "reference_counts": (payload.get("reference") or {}).get("counts"),
        "treatment_counts": (payload.get("treatment") or {}).get("counts"),
        "delta": payload.get("delta"),
        "ability_curve": payload.get("ability_curve"),
        "cases": payload.get("cases"),
    }


def _clause_resolve_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "same_mapping_for_both_variants": payload.get("same_mapping_for_both_variants"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "reference_counts": (payload.get("reference") or {}).get("counts"),
        "treatment_counts": (payload.get("treatment") or {}).get("counts"),
        "delta": payload.get("delta"),
        "cases": payload.get("cases"),
        "undecided_remains_searchable": payload.get("undecided_remains_searchable"),
    }


def _decision_contract_preview(payload: dict[str, object]) -> dict[str, object]:
    reference = payload.get("reference") or {}
    treatment = payload.get("treatment") or {}
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "same_mapping_for_both_variants": payload.get("same_mapping_for_both_variants"),
        "applied_to_v3": payload.get("applied_to_v3"),
        "reference_counts": reference.get("counts") if isinstance(reference, dict) else None,
        "treatment_counts": treatment.get("counts") if isinstance(treatment, dict) else None,
        "cases": payload.get("cases"),
        "approved_chain_does_not_upgrade_investigation": payload.get(
            "approved_chain_does_not_upgrade_investigation"
        ),
    }


def _gold_map_preview(payload: dict[str, object]) -> dict[str, object]:
    rematch = payload.get("rematch") or {}
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "version": payload.get("version"),
        "does_not_rewrite_history": payload.get("does_not_rewrite_history"),
        "avtal_160": payload.get("avtal_160"),
        "rematch_counts": rematch.get("counts") if isinstance(rematch, dict) else None,
        "answer_contract": payload.get("answer_contract"),
        "next_completion_replaces_yes_plus_hop": payload.get(
            "next_completion_replaces_yes_plus_hop"
        ),
    }


def _decision_trace_preview(payload: dict[str, object]) -> dict[str, object]:
    inspect = payload.get("inspect") or {}
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "blind_run_not_in_workspace": payload.get("blind_run_not_in_workspace"),
        "observability_gap": inspect.get("observability_gap") if isinstance(inspect, dict) else None,
        "do_not_guess_documents": inspect.get("do_not_guess_documents")
        if isinstance(inspect, dict)
        else None,
        "next": payload.get("next"),
    }


def _run_proof_found(config: IngestConfig) -> int:
    payload = run_proof_found(
        db_path=config.db_path,
        dense_dimension=config.dense_dimension or 3072,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_found_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_found_preview(payload: dict[str, object]) -> dict[str, object]:
    cases = []
    for row in payload.get("cases") or []:
        cases.append(
            {
                "relative_path": row.get("relative_path"),
                "gold_relevant": row.get("gold_relevant"),
                "first_yes": row.get("first_yes"),
                "explicit_relations_in_yes": row.get("explicit_relations_in_yes"),
                "hop_targets_from_yes": row.get("hop_targets_from_yes"),
                "final_rule": row.get("final_rule"),
                "evidence_span": {
                    "showable": (row.get("evidence_span") or {}).get("showable"),
                    "used_for_complete": (row.get("evidence_span") or {}).get("used_for_complete"),
                },
                "observed_v3": row.get("observed_v3"),
                "observed_gate": row.get("observed_gate"),
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "no_new_jev": payload.get("no_new_jev"),
        "hop_always_contract": payload.get("hop_always_contract"),
        "cases": cases,
    }


def _run_proof_gate(config: IngestConfig) -> int:
    client = None
    if config.typesafe_api_key:
        client = HttpJevClient(
            api_key=config.typesafe_api_key,
            base_url=config.typesafe_base_url,
        )
    payload = run_proof_gate(
        client=client,
        model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_gate_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_gate_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "does_not_replace_coverage_v3": payload.get("does_not_replace_coverage_v3"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "jev_prompt_unchanged": payload.get("jev_prompt_unchanged"),
        "proof_jev_rejected_for_standalone": payload.get("proof_jev_rejected_for_standalone"),
        "proof_gate_applied_to_v3": payload.get("proof_gate_applied_to_v3"),
        "reference_pass": payload.get("reference_pass"),
        "stacked_class_blocked": payload.get("stacked_class_blocked"),
        "false_complete_after_gate": payload.get("false_complete_after_gate"),
        "zero_false_complete": payload.get("zero_false_complete"),
        "inverted_exception": payload.get("inverted_exception"),
        "paraphrase_still_admitted": payload.get("paraphrase_still_admitted"),
        "jev_model": payload.get("jev_model"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def _run_proof_jev(config: IngestConfig) -> int:
    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --proof-jev", file=sys.stderr)
        return 2
    payload = run_proof_jev(
        client=HttpJevClient(
            api_key=config.typesafe_api_key,
            base_url=config.typesafe_base_url,
        ),
        model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
        concurrency=config.jev_concurrency,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_jev_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_jev_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "not_an_independent_blind_test": payload.get("not_an_independent_blind_test"),
        "zero_false_complete": payload.get("zero_false_complete"),
        "passed": payload.get("passed"),
        "judgment_count": payload.get("judgment_count"),
        "false_complete": payload.get("false_complete"),
        "hard_false_complete": payload.get("hard_false_complete"),
        "synonym_recall": payload.get("synonym_recall"),
        "insufficient_when_unlinked": payload.get("insufficient_when_unlinked"),
        "even_versus_inte": payload.get("even_versus_inte"),
        "versus_deterministic": payload.get("versus_deterministic"),
        "latency_ms_mean": payload.get("latency_ms_mean"),
        "total_tokens": payload.get("total_tokens"),
        "wall_seconds": payload.get("wall_seconds"),
        "groups": payload.get("groups"),
    }


def _run_proof_morph(config: IngestConfig) -> int:
    payload = run_proof_morph()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_morph_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_morph_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "detector_unchanged": payload.get("detector_unchanged"),
        "not_an_independent_blind_test": payload.get("not_an_independent_blind_test"),
        "case_count": payload.get("case_count"),
        "passed": payload.get("passed"),
        "failed": payload.get("failed"),
        "false_complete_count": payload.get("false_complete_count"),
        "synonym_recall": payload.get("synonym_recall"),
        "negation_false_complete": payload.get("negation_false_complete"),
        "even_versus_inte": payload.get("even_versus_inte"),
        "groups": payload.get("groups"),
    }


def _run_proof_link(config: IngestConfig) -> int:
    payload = run_proof_link()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_proof_work(config: IngestConfig) -> int:
    payload = run_proof_work()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_proof_contract(config: IngestConfig) -> int:
    payload = run_proof_contract()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_contract_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_contract_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "coverage_v3_unchanged": payload.get("coverage_v3_unchanged"),
        "no_new_controller": payload.get("no_new_controller"),
        "does_not_claim_saved_classifications": payload.get(
            "does_not_claim_saved_classifications"
        ),
        "relation": payload.get("relation"),
        "current_complete_at_first_signal": payload.get("current_complete_at_first_signal"),
        "proposed_complete_at_first_signal": payload.get("proposed_complete_at_first_signal"),
        "positives_expected": payload.get("positives_expected"),
        "needs_complementary": payload.get("needs_complementary"),
        "unresolved_references": payload.get("unresolved_references"),
        "control_none_complete": payload.get("control_none_complete"),
        "positives": [
            {
                "relative_path": row.get("relative_path"),
                "rank": row.get("rank"),
                "current": row.get("current"),
                "proposed": row.get("proposed"),
                "components": row.get("components"),
                "missing_components": row.get("missing_components"),
                "reference": row.get("reference"),
                "missing_coverage_parts": row.get("missing_coverage_parts"),
            }
            for row in payload.get("positives") or []
        ],
        "controls": [
            {
                "relative_path": row.get("relative_path"),
                "role": row.get("role"),
                "proposed": row.get("proposed"),
                "missing_components": row.get("missing_components"),
                "reference": row.get("reference"),
            }
            for row in payload.get("controls") or []
        ],
    }


def _run_proof_gap(config: IngestConfig) -> int:
    payload = run_proof_gap()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_proof_gap_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _proof_gap_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        ranking = item.get("ranking") or {}
        workspace = item.get("workspace") or {}
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "missing_complementary_passage": ranking.get("missing_complementary_passage"),
                "hop_possible": ranking.get("hop_possible"),
                "unseen_relevant_documents": ranking.get("unseen_relevant_documents"),
                "open_references": ranking.get("open_references"),
                "documents": ranking.get("documents"),
                "first_all_jev_yes_at": workspace.get("first_all_jev_yes_at"),
                "first_complete_evidence_at": workspace.get("first_complete_evidence_at"),
                "classifications_between_yes_and_complete": workspace.get(
                    "classifications_between_yes_and_complete"
                ),
                "hop_fetches": workspace.get("hop_fetches"),
                "hop_actions": workspace.get("hop_actions"),
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "coverage_v3_unchanged": payload.get("coverage_v3_unchanged"),
        "no_new_controller": payload.get("no_new_controller"),
        "work_kinds": payload.get("work_kinds"),
        "golds": golds,
    }


def _run_workspace_stop_replay(config: IngestConfig) -> int:
    payload = run_stop_replay()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_stop_replay_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _stop_replay_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "proof_kind": item.get("proof_kind"),
                "final_classified": item.get("final_classified"),
                "leftover_relevant_at_end": item.get("leftover_relevant_at_end"),
                "stops": [
                    {
                        "stop_budget": row.get("stop_budget"),
                        "observed_classified": row.get("observed_classified"),
                        "jev_yes_documents": row.get("jev_yes_documents"),
                        "complete_evidence_documents": row.get("complete_evidence_documents"),
                        "unresolved_documents": row.get("unresolved_documents"),
                        "saved_classifications": row.get("saved_classifications"),
                        "investigation_result": row.get("investigation_result"),
                        "unresolved_relevant_documents": row.get(
                            "unresolved_relevant_documents"
                        ),
                        "unresolved_kinds": row.get("unresolved_kinds"),
                        "next_jev_yes": row.get("next_jev_yes"),
                        "next_complete_evidence": row.get("next_complete_evidence"),
                    }
                    for row in item.get("stops") or []
                ],
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "coverage_v3_unchanged": payload.get("coverage_v3_unchanged"),
        "no_new_stop_rule": payload.get("no_new_stop_rule"),
        "replay_of_observed_path": payload.get("replay_of_observed_path"),
        "budget_exhausted_is_not_absent": payload.get("budget_exhausted_is_not_absent"),
        "investigation_results": payload.get("investigation_results"),
        "stop_budgets": payload.get("stop_budgets"),
        "golds": golds,
    }


def _run_evidence_curve(config: IngestConfig) -> int:
    payload = run_evidence_curves()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_evidence_preview(payload), ensure_ascii=False, indent=2))
    return 0


def _evidence_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        ranking = item.get("ranking") or {}
        workspace = item.get("workspace") or {}
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "ranking_checkpoints": ranking.get("checkpoints"),
                "ranking_increments": ranking.get("increments"),
                "workspace_checkpoints": workspace.get("checkpoints"),
                "workspace_increments": workspace.get("increments"),
                "unresolved_relevant_documents": workspace.get(
                    "unresolved_relevant_documents"
                ),
                "budget_exhausted_documents": workspace.get("budget_exhausted_documents"),
                "last_new_positive_at": workspace.get("last_new_positive_at"),
                "classifications_after_last_new_positive": workspace.get(
                    "classifications_after_last_new_positive"
                ),
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "do_not_optimize_first_yes": payload.get("do_not_optimize_first_yes"),
        "budget_exhausted_is_not_absent": payload.get("budget_exhausted_is_not_absent"),
        "evidence_contracts": payload.get("evidence_contracts"),
        "checkpoints": payload.get("checkpoints"),
        "golds": golds,
    }


def _run_analysis_cost(config: IngestConfig) -> int:
    payload = run_analysis_cost()
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_compare_embeddings(config: IngestConfig) -> int:
    report = run_embedding_compare(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            fusion_mode=config.fusion_mode,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        input_dir=config.input_dir,
        cache_dir=config.cache_dir,
        collection_id=config.collection_id,
        query_repeats=config.repeats,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_compare_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _compare_preview(payload: dict[str, object]) -> dict[str, object]:
    variants = []
    for item in payload.get("variants") or []:
        golds = []
        for gold in item.get("golds") or []:
            hybrid = (gold.get("modes") or {}).get("hybrid") or {}
            golds.append(
                {
                    "gold_id": gold.get("gold_id"),
                    "hybrid": hybrid,
                    "encode_seconds": gold.get("encode_seconds"),
                }
            )
        variants.append(
            {
                "id": item.get("id"),
                "dense_model": item.get("dense_model"),
                "sparse_encoder": item.get("sparse_encoder"),
                "dense_dimension": item.get("dense_dimension"),
                "embed_seconds": item.get("embed_seconds"),
                "cold_query_seconds": item.get("cold_query_seconds"),
                "warm_query_seconds": item.get("warm_query_seconds"),
                "engine_search_seconds": item.get("engine_search_seconds"),
                "peak_rss_mb": item.get("peak_rss_mb"),
                "golds": golds,
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "does_not_replace_c8": payload.get("does_not_replace_c8"),
        "default_retriever_unchanged": payload.get("default_retriever_unchanged"),
        "candidate_k": payload.get("candidate_k"),
        "peak_rss_mb": payload.get("peak_rss_mb"),
        "wall_seconds": payload.get("wall_seconds"),
        "variants": variants,
    }


def _run_decide_expansion(config: IngestConfig) -> int:
    report = run_expansion_decision(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        k=config.candidate_k,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_decision_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _decision_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "split": item.get("split"),
                "evaluation": item.get("evaluation"),
                "rule_expanded": item.get("rule_expanded"),
                "policies": item.get("policies"),
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "pipeline_stages": payload.get("pipeline_stages"),
        "rule": payload.get("rule"),
        "rule_is_hypothesis": payload.get("rule_is_hypothesis"),
        "verdict": payload.get("verdict"),
        "default_retriever_unchanged": payload.get("default_retriever_unchanged"),
        "k": payload.get("k"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_profile_retrieval(config: IngestConfig) -> int:
    report = run_retrieval_profile(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            fusion_mode=config.fusion_mode,
        ),
        repeats=config.repeats,
        k=config.candidate_k,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_profile_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _profile_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "previous_dense_sparse_seconds_were_python_exhaustive": payload.get(
            "previous_dense_sparse_seconds_were_python_exhaustive"
        ),
        "dense_and_sparse_run_sequentially": payload.get("dense_and_sparse_run_sequentially"),
        "do_not_optimize_engine": payload.get("do_not_optimize_engine"),
        "units": payload.get("units"),
        "k": payload.get("k"),
        "repeats": payload.get("repeats"),
        "corpus": payload.get("corpus"),
        "headline": payload.get("headline"),
    }


def _run_expand_queries(config: IngestConfig) -> int:
    report = run_query_expansion(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        ks=config.ks,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_expand_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _expand_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "split": item.get("split"),
                "concept": item.get("concept"),
                "terms": item.get("terms"),
                "latency": item.get("latency"),
                "delta_at_50": item.get("delta_at_50"),
                "variants": {
                    name: {
                        "query": row.get("query"),
                        "modes": {
                            mode: {
                                "recall_at_50": metrics.get("recall_at_50"),
                                "document_coverage_at_50": metrics.get(
                                    "document_coverage_at_50"
                                ),
                                "hard_negatives_at_50": metrics.get("hard_negatives_at_50"),
                                "units_to_document_recall": metrics.get(
                                    "units_to_document_recall"
                                ),
                            }
                            for mode, metrics in (row.get("modes") or {}).items()
                        },
                    }
                    for name, row in (item.get("variants") or {}).items()
                },
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "dense_model": payload.get("dense_model"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_coverage(config: IngestConfig) -> int:
    report = run_coverage(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        global_k=config.coverage_global_k,
        per_document=config.coverage_per_document,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_coverage_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _coverage_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        scorers = {}
        for mode, strategies in (item.get("scorers") or {}).items():
            scorers[mode] = {
                name: {
                    "document_recall": row.get("document_recall"),
                    "evidence_recall": row.get("evidence_recall"),
                    "would_be_jev_calls": row.get("would_be_jev_calls"),
                    "extra_units": row.get("extra_units"),
                    "curve": (row.get("curve") or {}).get("units_to_document_recall"),
                    "missed_relevant_documents": row.get("missed_relevant_documents"),
                    "touched_relevant_without_evidence": row.get(
                        "touched_relevant_without_evidence"
                    ),
                    "false_negative_documents": row.get("false_negative_documents"),
                    "status_counts": row.get("status_counts"),
                }
                for name, row in strategies.items()
            }
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "relevant_documents": item.get("relevant_documents"),
                "wall_seconds": item.get("wall_seconds"),
                "scorers": scorers,
            }
        )
    return {
        "operation": payload.get("operation"),
        "controller": payload.get("controller"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "global_k": payload.get("global_k"),
        "per_document": payload.get("per_document"),
        "units": payload.get("units"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_navigation(config: IngestConfig) -> int:
    report = run_navigation(db_path=config.db_path, dense_dimension=config.dense_dimension)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report.payload, ensure_ascii=False, indent=2))
    return 0


def _run_jev(config: IngestConfig) -> int:
    report = run_jev_classification(
        JevRunConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            candidates_path=config.candidates_path,
            dense_dimension=config.dense_dimension,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            experiment=config.jev_experiment,
            batch_size=config.jev_batch_size,
            concurrency=config.jev_concurrency,
            baseline_path=config.jev_baseline_path,
            candidate_strategy=config.candidate_strategy,
            candidate_k=config.candidate_k,
            timeout_seconds=config.jev_timeout_seconds,
        )
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_jev_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _jev_preview(payload: dict[str, object]) -> dict[str, object]:
    runs = []
    for item in payload.get("runs") or []:
        runs.append(
            {
                "variant": item.get("variant"),
                "context": item.get("context"),
                "batch_size": item.get("batch_size"),
                "concurrency": item.get("concurrency"),
                "precision": item.get("precision"),
                "recall": item.get("recall"),
                "predicted": item.get("predicted"),
                "false_positives": [
                    row.get("relative_path") for row in (item.get("false_positives") or [])
                ],
                "false_negatives": [
                    row.get("relative_path") for row in (item.get("false_negatives") or [])
                ],
                "watch_predicted_yes": [
                    row.get("relative_path") for row in (item.get("watch_predicted_yes") or [])
                ],
                "uncertain_relevant": len(item.get("uncertain_relevant") or []),
                "document_recall": item.get("document_recall"),
                "hard_negative_predictions": [
                    {
                        "relative_path": row.get("relative_path"),
                        "gold_label": row.get("gold_label"),
                        "predicted": row.get("predicted"),
                    }
                    for row in (item.get("hard_negative_predictions") or [])
                ],
                "coverage_groups": item.get("coverage_groups"),
                "versus_baseline": _delta_preview(item.get("versus_baseline")),
                "versus_reference": _delta_preview(item.get("versus_reference")),
                "speedup_vs_reference": item.get("speedup_vs_reference"),
                "model_calls": item.get("model_calls"),
                "wall_seconds": item.get("wall_seconds"),
                "errors": item.get("errors"),
            }
        )
    return {
        "experiment": payload.get("experiment"),
        "gold_id": payload.get("gold_id"),
        "kind": payload.get("kind"),
        "classify_question": payload.get("classify_question"),
        "jev_model": payload.get("jev_model"),
        "candidates": payload.get("candidates"),
        "candidate_strategy": payload.get("candidate_strategy"),
        "candidate_k": payload.get("candidate_k"),
        "runs": runs,
    }


def _delta_preview(delta: object) -> dict[str, object] | None:
    if not isinstance(delta, dict):
        return None
    return {
        "changed": len(delta.get("changed") or []),
        "improvements": len(delta.get("improvements") or []),
        "regressions": len(delta.get("regressions") or []),
        "retained_true_yes": delta.get("retained_true_yes"),
        "watched": [
            {
                "relative_path": row.get("relative_path"),
                "from": row.get("from"),
                "to": row.get("to"),
            }
            for row in (delta.get("watched") or [])
        ],
    }


def _run_jev_property_verification(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.jev_property_verify import (
        ROOT as VERIFY_ROOT,
    )
    from overgraph_ingest.retrieval.jev_property_verify import (
        run_jev_property_verification,
        write_verification_baseline,
        write_verification_report,
    )

    if config.jev_property_review is None:
        print("--jev-property-review is required", file=sys.stderr)
        return 2
    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --jev-property-verification", file=sys.stderr)
        return 2
    dimension = config.dense_dimension or 3072
    try:
        report = run_jev_property_verification(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
            ),
            review_path=config.jev_property_review,
            taxonomy_path=config.property_taxonomy,
            mapping_path=config.property_gold_mapping,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            jev_timeout_seconds=config.jev_timeout_seconds,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Jev property verification blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = (
        config.output_path.with_suffix(".md")
        if config.output_path is not None
        else VERIFY_ROOT / "eval" / "jev-property-verification-v1.md"
    )
    write_verification_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_verification_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(_verification_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _verification_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "groups": payload.get("groups"),
        "metrics": payload.get("metrics"),
        "decision": payload.get("decision"),
        "manifest": payload.get("manifest"),
    }


def _run_jev_end_to_end(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.jev_end_to_end import ROOT as E2E_ROOT
    from overgraph_ingest.retrieval.jev_end_to_end import (
        run_jev_end_to_end,
        write_e2e_baseline,
        write_e2e_report,
    )

    if config.jev_property_review is None:
        print("--jev-property-review is required", file=sys.stderr)
        return 2
    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --jev-end-to-end", file=sys.stderr)
        return 2
    dimension = config.dense_dimension or 3072
    try:
        report = run_jev_end_to_end(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
            ),
            review_path=config.jev_property_review,
            taxonomy_path=config.property_taxonomy,
            mapping_path=config.property_gold_mapping,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            jev_timeout_seconds=config.jev_timeout_seconds,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            local_k=config.jev_local_k,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Jev end-to-end blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = (
        config.output_path.with_suffix(".md")
        if config.output_path is not None
        else E2E_ROOT / "eval" / "jev-end-to-end-v1.md"
    )
    write_e2e_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_e2e_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(_e2e_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _e2e_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "groups": payload.get("groups"),
        "metrics": payload.get("metrics"),
        "manifest": payload.get("manifest"),
    }


def _run_jev_local_abc(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.jev_local_query_abc import (
        ABC_BASELINE_PATH,
        DEFAULT_EVIDENCE_QUERIES,
        run_jev_local_query_abc,
        write_abc_baseline,
        write_abc_report,
    )

    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --jev-local-abc", file=sys.stderr)
        return 2
    if not config.openai_api_key:
        print("--openai-api-key is required with --jev-local-abc", file=sys.stderr)
        return 2
    dimension = config.dense_dimension or 3072
    try:
        report = run_jev_local_query_abc(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
            ),
            baseline_path=config.jev_local_baseline,
            evidence_queries_path=config.jev_evidence_queries or DEFAULT_EVIDENCE_QUERIES,
            taxonomy_path=config.property_taxonomy,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            jev_timeout_seconds=config.jev_timeout_seconds,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            local_k=config.jev_local_k,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Jev local A/B/C blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = (
        config.output_path.with_suffix(".md")
        if config.output_path is not None
        else ABC_BASELINE_PATH.parent.parent / "eval" / "jev-local-query-abc-v1.md"
    )
    write_abc_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_abc_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(report.payload["arms"], ensure_ascii=False, indent=2))
    return 0


def _run_jev_presentation(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.jev_presentation_v1 import (
        PRESENT_BASELINE_PATH,
        DEFAULT_EVIDENCE_QUERIES,
        run_jev_presentation_v1,
        write_presentation_baseline,
        write_presentation_report,
    )

    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --jev-presentation", file=sys.stderr)
        return 2
    if not config.openai_api_key:
        print("--openai-api-key is required with --jev-presentation", file=sys.stderr)
        return 2
    dimension = config.dense_dimension or 3072
    try:
        report = run_jev_presentation_v1(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
            ),
            baseline_path=config.jev_local_baseline,
            evidence_queries_path=config.jev_evidence_queries or DEFAULT_EVIDENCE_QUERIES,
            taxonomy_path=config.property_taxonomy,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            jev_timeout_seconds=config.jev_timeout_seconds,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            local_k=config.jev_local_k,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Jev presentation blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = (
        config.output_path.with_suffix(".md")
        if config.output_path is not None
        else PRESENT_BASELINE_PATH.parent.parent / "eval" / "jev-presentation-v1.md"
    )
    write_presentation_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_presentation_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(report.payload["arms"], ensure_ascii=False, indent=2))
    return 0


def _run_jev_validation(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.jev_validation_v1 import (
        VALIDATION_BASELINE_PATH,
        run_jev_validation,
        write_validation_baseline,
        write_validation_report,
    )

    if not config.typesafe_api_key:
        print("--typesafe-api-key is required with --jev-validation", file=sys.stderr)
        return 2
    if not config.openai_api_key:
        print("--openai-api-key is required with --jev-validation", file=sys.stderr)
        return 2
    dimension = config.dense_dimension or 3072
    try:
        report = run_jev_validation(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
            ),
            taxonomy_path=config.property_taxonomy,
            mapping_path=config.property_gold_mapping,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            jev_timeout_seconds=config.jev_timeout_seconds,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            local_k=config.jev_local_k,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Jev validation blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = (
        config.output_path.with_suffix(".md")
        if config.output_path is not None
        else VALIDATION_BASELINE_PATH.parent.parent / "eval" / "jev-validation-v1.md"
    )
    write_validation_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_validation_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(
        {
            "groups": report.payload["groups"],
            "totals": report.payload["metrics"]["totals"],
            "recall_loss": report.payload["metrics"]["recall_loss"],
            "uncertain_share": report.payload["metrics"]["uncertain_share"],
            "local_dense": report.payload["metrics"]["local_dense"],
            "latency_ms": report.payload["metrics"]["latency_ms"],
            "jev_calls": report.payload["metrics"]["jev_calls"],
            "preliminary_agreement_30": report.payload["metrics"]["preliminary_agreement_30"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def _run_document_properties(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.document_properties import (
        ROOT as PROPERTIES_ROOT,
    )
    from overgraph_ingest.retrieval.document_properties import (
        run_document_properties,
        write_document_properties_baseline,
        write_document_properties_report,
    )

    if config.property_track != "structure":
        print("only --property-track structure is implemented", file=sys.stderr)
        return 2
    dimension = config.dense_dimension or 3072
    try:
        report = run_document_properties(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
            ),
            taxonomy_path=config.property_taxonomy,
            mapping_path=config.property_gold_mapping,
            bm25_run_path=config.property_bm25_run,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"document properties blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = (
        config.output_path.with_suffix(".md")
        if config.output_path is not None
        else PROPERTIES_ROOT / "eval" / "document-properties-v1.md"
    )
    write_document_properties_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_document_properties_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(_document_properties_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _document_properties_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "track": payload.get("track"),
        "taxonomy_hash": payload.get("taxonomy_hash"),
        "mapping_hash": payload.get("mapping_hash"),
        "macro": payload.get("macro"),
        "manifest": payload.get("manifest"),
    }


def _run_discovery(config: IngestConfig) -> int:
    from overgraph_ingest.retrieval.discovery import (
        ROOT as DISCOVERY_ROOT,
    )
    from overgraph_ingest.retrieval.discovery import (
        run_document_discovery,
        write_discovery_baseline,
        write_discovery_report,
    )

    dimension = config.dense_dimension or 3072
    try:
        report = run_document_discovery(
            RetrievalConfig(
                db_path=config.db_path,
                dense_dimension=dimension,
                write_batch_size=config.write_batch_size,
                dense_model=config.dense_model,
                openai_api_key=config.openai_api_key,
                openai_base_url=config.openai_base_url,
            )
        )
    except (ValueError, RuntimeError) as exc:
        print(f"document discovery blocked: {exc}", file=sys.stderr)
        return 2
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    report_path = config.output_path.with_suffix(".md") if config.output_path is not None else DISCOVERY_ROOT / "eval" / "document-discovery-v1.md"
    write_discovery_report(report.payload, report_path)
    if config.freeze_baseline:
        try:
            baseline = write_discovery_baseline(report.payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline}", file=sys.stderr)
    print(json.dumps(_discovery_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _discovery_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "hypothesis": payload.get("hypothesis"),
        "equal_budget_docs": payload.get("equal_budget_docs"),
        "macro": payload.get("macro"),
        "manifest": payload.get("manifest"),
    }


def _run_bm25_compare(config: IngestConfig) -> int:
    from overgraph_ingest.graph.writer import (
        GraphWriter,
        open_database,
        resolve_dimension,
    )
    from overgraph_ingest.jev.candidates import load_graph_context
    from overgraph_ingest.retrieval.bm25 import SV_PLAIN, SV_STEM
    from overgraph_ingest.retrieval.bm25_answer import run_bm25_answer_test
    from overgraph_ingest.retrieval.bm25_run import (
        DEFAULT_GOLD_DIR,
        DEFAULT_INDEX_DIR,
        DEFAULT_OVERLAY,
        GLOBAL_KS,
        run_bm25_experiment,
        run_paging_test,
        write_bm25_baseline,
        write_bm25_report,
    )
    from overgraph_ingest.retrieval.evidence_gold import load_question_gold
    from overgraph_ingest.retrieval.index import load_published_units

    analyzers = (
        (SV_STEM, SV_PLAIN)
        if config.bm25_analyzer == "both"
        else (config.bm25_analyzer,)
    )
    global_ks = tuple(k for k in config.ks if k in GLOBAL_KS) or GLOBAL_KS
    gold_dir = config.bm25_gold_dir or DEFAULT_GOLD_DIR
    question_gold = config.bm25_question_gold
    if question_gold is None and DEFAULT_OVERLAY.is_file():
        question_gold = DEFAULT_OVERLAY
    cells = (
        load_question_gold(question_gold)
        if config.bm25_scope in {"document", "both"} or config.bm25_answer_test
        else []
    )
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    payload: dict[str, object]
    if config.bm25_candidates is not None and config.bm25_answer_test:
        payload = json.loads(config.bm25_candidates.read_text(encoding="utf-8"))
        db = open_database(config.db_path, dimension)
        try:
            context = load_graph_context(GraphWriter(db, batch_size=config.write_batch_size))
        finally:
            db.close()
        units = context.units
        structures = context.structures
    else:
        structures = None
        if config.bm25_answer_test:
            db = open_database(config.db_path, dimension)
            try:
                context = load_graph_context(
                    GraphWriter(db, batch_size=config.write_batch_size)
                )
            finally:
                db.close()
            units = context.units
            structures = context.structures
        else:
            db = open_database(config.db_path, dimension)
            try:
                units = load_published_units(
                    GraphWriter(db, batch_size=config.write_batch_size)
                )
            finally:
                db.close()
        try:
            payload = run_bm25_experiment(
                RetrievalConfig(
                    db_path=config.db_path,
                    dense_dimension=dimension,
                    write_batch_size=config.write_batch_size,
                    dense_model=config.dense_model,
                    openai_api_key=config.openai_api_key,
                    openai_base_url=config.openai_base_url,
                    fusion_mode=config.fusion_mode,
                    ks=global_ks,
                ),
                gold_dir=gold_dir,
                question_gold_path=question_gold,
                scope=config.bm25_scope,
                analyzers=analyzers,
                index_dir=config.bm25_index_dir or DEFAULT_INDEX_DIR,
                branch_depth=config.bm25_branch_depth,
                global_ks=global_ks,
                local_ks=config.bm25_local_ks,
                repeats=config.bm25_repeats,
                units=units,
                cells=cells,
            )
        except (ValueError, RuntimeError) as exc:
            print(f"BM25 measurement blocked: {exc}", file=sys.stderr)
            return 2
    if config.bm25_answer_test:
        try:
            answer = run_bm25_answer_test(
                payload,
                units=units,
                cells=cells,
                structures=structures,
                typesafe_api_key=config.typesafe_api_key,
                typesafe_base_url=config.typesafe_base_url,
                jev_model=config.jev_model,
                jev_timeout_seconds=config.jev_timeout_seconds,
                profile=analyzers[0],
            )
        except (ValueError, RuntimeError) as exc:
            answer = {
                "operation": "bm25_answer_test",
                "status": "blocked",
                "measurement_status": "blocked",
                "blocked_reason": str(exc),
                "claim_scope": "improved_retrieval_only",
            }
        payload["answer_test"] = answer
        payload["claim_scope"] = answer.get("claim_scope")
    if config.bm25_paging:
        payload["paging"] = run_paging_test(
            payload,
            page_size=config.bm25_page_size,
            profile=analyzers[0],
        )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if config.freeze_baseline:
        try:
            baseline = write_bm25_baseline(payload)
            report = write_bm25_report(payload)
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"wrote {baseline} and {report}", file=sys.stderr)
    print(json.dumps(_bm25_preview(payload), ensure_ascii=False, indent=2))
    answer_status = (payload.get("answer_test") or {}).get("status")
    if payload.get("status") != "completed" or answer_status == "blocked":
        return 2
    return 0


def _bm25_preview(payload: dict[str, object]) -> dict[str, object]:
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "status": payload.get("status"),
        "claim_scope": payload.get("claim_scope"),
        "default_retriever_unchanged": payload.get("default_retriever_unchanged"),
        "production_changed": payload.get("production_changed"),
        "verdict": payload.get("verdict"),
        "summary": payload.get("summary"),
        "answer_test": {
            "status": (payload.get("answer_test") or {}).get("status")
            if isinstance(payload.get("answer_test"), dict)
            else None,
            "blocked_reason": (payload.get("answer_test") or {}).get("blocked_reason")
            if isinstance(payload.get("answer_test"), dict)
            else None,
        },
        "paging": {
            "status": (payload.get("paging") or {}).get("status")
            if isinstance(payload.get("paging"), dict)
            else None,
            "page_size": (payload.get("paging") or {}).get("page_size")
            if isinstance(payload.get("paging"), dict)
            else None,
        },
        "manifest": payload.get("manifest"),
    }


def _run_retrieval(config: IngestConfig) -> int:
    report = run_retrieval(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            embed=config.embed,
            fusion_mode=config.fusion_mode,
            ks=config.ks,
        )
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_retrieval_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _parse_ks(raw: str) -> tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise ValueError("--k must contain at least one integer")
    return values


def _parse_budgets(raw: str) -> tuple[int | None, ...]:
    values: list[int | None] = []
    for part in raw.split(","):
        if not part.strip():
            continue
        number = int(part.strip())
        values.append(None if number == 0 else number)
    if not values:
        raise ValueError("--coverage-budgets must contain at least one integer")
    return tuple(values)


def _retrieval_preview(payload: dict[str, object]) -> dict[str, object]:
    strategies = payload.get("strategies") or {}
    preview = {
        "gold_id": payload.get("gold_id"),
        "query": payload.get("query"),
        "dense_model": payload.get("dense_model"),
        "sparse_encoder": payload.get("sparse_encoder"),
        "units": payload.get("units"),
        "relevant_units_in_graph": payload.get("relevant_units_in_graph"),
        "hard_negatives_in_graph": payload.get("hard_negatives_in_graph"),
        "absent_from_graph": len(payload.get("absent_from_graph") or []),
        "strategies": {},
    }
    for name, block in strategies.items():
        at_k = block.get("at_k") or {}
        preview["strategies"][name] = {
            "ranking": block.get("ranking"),
            "at_k": {
                k: {
                    "recall": cell.get("recall"),
                    "precision": cell.get("precision"),
                    "document_coverage": cell.get("document_coverage"),
                    "unique_documents": cell.get("unique_documents"),
                    "mrr": cell.get("mrr"),
                    "document_mrr": cell.get("document_mrr"),
                    "ndcg": cell.get("ndcg"),
                    "first_relevant_rank": cell.get("first_relevant_rank"),
                    "hard_negatives_in_topk": cell.get("hard_negatives_in_topk"),
                    "hard_negative_ranks": cell.get("hard_negative_ranks"),
                    "unretrieved": len(cell.get("unretrieved") or []),
                    "low_rank": len(cell.get("low_rank") or []),
                }
                for k, cell in at_k.items()
            },
        }
    return preview


def _run_gold(config: IngestConfig) -> int:
    gold_dir = config.gold_dir or (config.db_path.parent / "gold" / "synthetic")
    generate_gold_set(gold_dir)
    scores = evaluate_gold_dir(gold_dir, config, origin="synthetic")
    payload = summarize_scores(scores)
    if config.real_gold_dir is not None:
        payload = {
            "synthetic": payload,
            "real": summarize_scores(
                evaluate_gold_dir(config.real_gold_dir, config, origin="real")
            ),
        }
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    structure_errors = (
        payload.get("structure_errors")
        if "structure_errors" in payload
        else payload.get("synthetic", {}).get("structure_errors", 0)
    )
    return 0 if structure_errors == 0 else 1


def _suite_preview(payload: dict[str, object]) -> dict[str, object]:
    quality = payload.get("quality") or {}
    synthetic = quality.get("synthetic") or {}
    return {
        "environment": payload.get("environment"),
        "scaling": payload.get("scaling"),
        "preparation": payload.get("preparation"),
        "quality": {
            "synthetic_structure_errors": synthetic.get("structure_errors"),
            "synthetic_perfect_cases": synthetic.get("perfect_cases"),
            "synthetic_mean_clause_recall": synthetic.get("mean_clause_recall"),
            "real": quality.get("real"),
        },
        "experiments": {
            name: {
                "total_seconds": block.get("total_seconds"),
                "extraction_seconds": block.get("extraction_seconds"),
                "overgraph_persist_seconds": block.get("overgraph_persist_seconds"),
                "last_headline": block.get("last_headline"),
            }
            for name, block in (payload.get("experiments") or {}).items()
        },
        "batch_sizes": {
            name: block.get("overgraph_persist_seconds")
            for name, block in (payload.get("batch_sizes") or {}).items()
        },
        "output": "full JSON written to --output when set",
    }
