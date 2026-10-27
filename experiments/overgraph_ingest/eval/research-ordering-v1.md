# Research ordering v1 — scans-until-covered per strategy on the clause golds

Frozen before conclusions. This is the measurement specified in
`docs/architecture/research-ordering-measurement-spec.md`, executed on the
suite's frozen stack. No production code changed; no live model calls beyond
five query embeddings (text-embedding-3-large).

## Method

- Corpus: `data/extra-overgraph-phase2` (2548 TextUnits, all documents).
- Five clause golds from `retrieval_gold/`; relevant counts 20/13/34/13/7.
- Strategies: `dense` (text-embedding-3-large), `sparse` (lexical-tfidf-hash-v1),
  `hybrid` (reciprocal-rank fusion), `union_rrf`, `union_pool`.
- `scans-until-covered` = smallest k in the fine k-grid where recall = 1.0;
  `>100` means recall never reaches 1.0 within k=100.
- Reproduction run with `--k 5,10,15,...,100`; drift check against the frozen
  `retrieval-*.json` artifacts: identical on recall@100 for all five strategies
  and all five questions.

## Result

| Question | dense | sparse | hybrid | union_rrf | union_pool | oracle |
|---|---|---|---|---|---|---|
| auto-renewal | >100 | 70 | **30** | 70 | 30 | 20 |
| notice-period | >100 | >100 | >100 | >100 | **90** | 13 |
| liability-cap | >100 | 100 | **80** | 100 | 80 | 34 |
| confidentiality | **90** | >100 | >100 | >100 | 90 | 13 |
| liability-secrecy-carveout | 60 | **10** | 15 | 35 | 15 | 7 |

## Verdict against the spec's decision rule

**Not met.** The spec required hybrid to beat lexical (sparse) by ≥2× on the
median before proposing any production change. Measured: hybrid beats sparse
≥2× on exactly one of five questions (auto-renewal 70→30); on
liability-secrecy-carveout pure lexical wins outright (10 vs 15); on
notice-period and confidentiality no strategy reaches full recall within
k=100. **No production change is proposed from this measurement.**

Three findings worth carrying forward:

1. **Pure semantic ordering is insufficient on the full 2548-unit universe**:
   dense alone misses full recall within k=100 on three of five questions. The
   earlier 9–15× similarity result was measured on a per-question corpus of
   only the gold documents; on the all-documents universe the ranking problem
   is harder and pure dense degrades.
2. **The union fusions are the robust candidates**: `union_pool` is the only
   strategy that reaches full recall within k=100 on every question.
3. **The best strategy varies per question** (lexical wins carveout, hybrid
   wins auto-renewal and liability-cap, dense wins confidentiality) — a fixed
   global ordering choice is not obviously optimal.

## Caveats

- The suite's `sparse` is lexical-tfidf, not production's Tantivy BM25 or the
  OverGraph engine's sparse. The production-engine comparison (engine hybrid
  vs Tantivy on this gold) is the next fidelity step.
- The JEV screening stage was measured over hybrid top-50 for auto-renewal
  only (20/20 relevant in candidates, precision 0.95). JEV-over-candidates
  coverage for the other four questions is unmeasured.
- The research loop may not need recall=1.0 from retrieval alone
  (gap planning and followups exist); this metric is a retrieval ceiling, not
  an end-to-end quality claim.

## Frozen artifacts

- Baseline: `experiments/overgraph_ingest/baselines/research-ordering-v1.json`
- Contract: `experiments/overgraph_ingest/tests/test_research_ordering.py`
