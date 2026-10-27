# Research ordering measurement spec — does semantic sorting improve research?

Status: measurement proposal. **Changes no production code and makes no model
calls.** Audience: agents working in the research pipeline or the ingest suite.

## Purpose

Quantify whether ordering research candidates by semantic similarity (dense
embeddings) reduces the number of text segments that must be scanned before
all gold evidence is covered, relative to lexical ordering and to the current
production ordering. The swe-gym experiment measured a 9–15× reduction on five
clause questions with external embeddings (see
`docs/SWE_Sweycoins_resultat.md`); this spec measures the same question inside
the repo's own measurement stack — offline, against frozen gold, with the
local BGE-M3 encoder.

## The question, exactly

For a fixed question with frozen gold evidence units `E` (`|E| = e`) and a
candidate ordering `O` over the segment universe:

```text
scans(O)   = index of the last gold unit under O      # the gym metric
oracle     = e                                        # perfect ordering floor
blind      = segment count                            # document-order ceiling
```

Compare `O ∈ {lexical (BM25), semantic (BGE-M3 dense), production}` on
`scans` plus the suite-standard ranking metrics below.

## Reuse-vs-new matrix

| Piece | Existing counterpart | Decision |
|---|---|---|
| Gold spans + hard negatives | `experiments/overgraph_ingest/retrieval_gold/` + holdouts frozen pre-model (`eval/holdout-gold-v1.md`) | **Reuse** |
| Lexical ordering | `overgraph_ingest/retrieval/bm25.py` (`tuned_on_gold=False`) | **Reuse** |
| Semantic ordering | `overgraph_ingest/retrieval/bge_m3.py` (local encoder, no API) | **Reuse** |
| Production ordering | `experiments/overgraph_ingest/baselines/` frozen overgraph-search baseline (`conclusions.load_overgraph_search_baseline`) | **Reuse + fidelity check** |
| Ranking metrics | `overgraph_ingest/retrieval/evaluate.py` (recall, NDCG, `first_relevant_rank`, `hard_negative_ranks`) | **Reuse** |
| Budget/scan curves | `overgraph_ingest/retrieval/two_stage.py` (`stage1_curve`, `score_allocation`) | **Reuse** |
| Frozen baseline loaders | `overgraph_ingest/retrieval/conclusions.py` | **Reuse** |
| Document-level gold | `synthetic_sme/ground_truth/coverage_matrix.json` (200 GQs, `requires_data`) + `facit.json` | **Reuse** (deferred) |
| Facit-isolation cross-check | swe-gym `benchmarks/bench_real_v2.json` + `real_fixtures/` | **Reuse** |
| Glue script + production-ordering replay adapter + report + one CI contract test | — | **New** — justified: nothing in the repo currently orders the production path against the suite's gold |

Every new piece is measurement plumbing, not a new model or abstraction, and
the contract test reuses the `tests/research_reuse` pattern.

## Metrics (primary first)

1. **`scans-until-covered`** per question and median across the five clause
   questions — the operational measure of "how far must the pipeline read".
2. **Recall@k curves** (k = 10, 25, 50, 100) per ordering.
3. **`first_relevant_rank`** and **`hard_negative_ranks`** — no hard-negative
   rank regression is permitted against the current best ordering.
4. **Document-level early-rank** over the 200 SPEC-SME GQs: the rank of the
   last `requires_data` document under each ordering.
5. **Oracle floor** per question, reported next to every number for context.

## Frozen-data discipline

- No gold is used for tuning anything; ordering computation never sees the
  evidence sets (facit isolation, as in the swe-gym bench).
- Holdouts stay frozen. The five clause golds and SPEC-SME remain the facit.
- The report follows the `eval/*-v1.md` format; new baselines freeze under
  `experiments/overgraph_ingest/baselines/` like the `phase2-*` files.

## Procedure

1. Reproduce the existing BM25-vs-BGE-M3 comparison on the frozen holdouts —
   sanity and drift check of the measurement stack.
2. Replay the production ordering from the frozen overgraph-search baseline,
   after verifying it matches today's `need_retrieval`/`result_search`
   ordering semantics (open question 1).
3. Compute all five metrics for all three orderings over the five clause
   questions.
4. Run the document-level pass over the 200 SPEC-SME GQs.
5. Freeze the report in `eval/` and add one CI contract test pinning the
   measured relations once they hold.

## Decision rule

No production change is proposed unless, on frozen gold: semantic ordering
reduces the median `scans-until-covered` versus the production ordering by
**≥2×, fixed before reading results (decided 2026-10-26)**, with no
hard-negative rank regression. The spec itself changes nothing; it only
produces the decision basis.

## Guardrails / non-goals

- No live API calls (BGE-M3 runs locally; production ordering comes from
  frozen baselines).
- No scripted scores presented as model quality — deterministic ordering
  measurement only.
- No new models, tables, frameworks, or production code — per the
  reuse-before-new standard.

## Fidelity check (done 2026-10-26)

Production's passage retrieval is already hybrid, not lexical-only:

- `KnowledgeResearchSource` (`backend/app/services/research/knowledge_source.py`)
  → Overgraph search (`backend/app/services/overgraph/catalogs.py`) accepts
  both `dense_query` and `sparse_query`; dense vectors come from
  `text-embedding-3-large` (3072 dims) — the same encoder as the swe-gym
  similarity ordering that produced the 9–15× result.
- `result_search._graph_seeds` augments candidates with hybrid fact hits.

The frozen baseline `phase2-overgraph-hybrid-search.json` measures the same
mechanism (Overgraph engine hybrid, k=50, 2548 TextUnits,
`text-embedding-3-large`) but is an experimental snapshot, not today's
production number: its own flags say `do_not_overwrite`,
`does_not_replace_c8`, `do_not_optimize_engine`, and the suite treats the
official classify baseline (c8) separately.

**Consequence:** the production-order measurement must replay the actual
production candidate path (`KnowledgeResearchSource` → Overgraph catalogs
hybrid) offline against the same gold. The frozen baseline serves as a drift
reference. Because production is already hybrid, the comparison frame gains a
fourth reference: production hybrid vs pure BM25 vs pure BGE-M3 vs the
gym's measured similarity ordering (38/26/47/18/16 scans on the five clause
questions).

## Decisions (fixed before measurement)

1. **Threshold:** ≥2× median `scans-until-covered` reduction required to
   propose a production change.
2. **Scope:** clause questions first (`retrieval_gold/`, five questions).
   The SPEC-SME document-level pass is deferred.
3. **Fidelity:** replay the production candidate path itself; the frozen
   hybrid baseline is a drift reference only.

## Open questions

1. Does the production hybrid ordering reproduce the gym's similarity-order
   numbers on the five clause golds, or does the sparse component pull it
   toward lexical behavior?
2. Is a pure-dense ordering meaningfully better than production's hybrid on
   this gold, or is hybrid already at the optimum?
