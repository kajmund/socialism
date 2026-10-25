# Tantivy index strategies: inventory and first benchmark

Status: inventory + isolated benchmark. **No production change.** PR #432 stays
open and `write_paths_ready=false`. The durable generation/tombstone design is
in [tantivy-generation-ledger.md](tantivy-generation-ledger.md).

## Existing index (already implemented)

- `app/services/tantivy_index.py` builds a derived index from OverGraph
  TextUnits/Facts: BM25 with Swedish stemming, tenant/document filters,
  fact subword index, deterministic key pagination.
- Full rebuild: `build_from_overgraph` writes a temporary index and atomically
  swaps `current`; build start is written as the watermark.
- Incremental: `pending_updates` counts nodes whose OverGraph `updated_at` is
  newer than the watermark; `reconcile` pages by time range and upserts by key.
  At-least-once; callers persist the new watermark only after success.
- Deletion: `TextUnitIndex.delete_keys` exists but **is not called by reconcile**
  and has no production caller. A deleted TextUnit/Fact therefore remains in the
  index; hydration filters some fact cases but lexical candidates can still be
  stale.
- `retrieval_index` is process-local and owner mode currently disables it. There
  is no generation token beyond the millisecond watermark.
- Index maintenance is not wired into owner ingestion; owner mode fails closed
  instead of serving a stale index.

## Alternatives

| Option | Shape | Key question |
| --- | --- | --- |
| A. Local index per backend | each backend owns a derived index | synchronization and duplicate work |
| B. Tantivy in Owner process | one derived index per catalog, searches on owner read executor | does search hurt mutation latency? |
| C. Separate index process | isolated CPU, own lifecycle | is extra ops + consistency worth it? |
| D. Overgraph only | dense/vector + graph retrieval, no lexical index | is Tantivy needed for these searches? |

All A/B/C share the same Tantivy build/search code; the difference is placement,
lifecycle and synchronization. Any option needs a deletion/generation model;
today's watermark handles upserts but not removals.

## Synthetic benchmark

`backend/scripts/benchmark_tantivy_strategies.py` (200 facts, 5 categories,
40 facts/category; half contain the exact category term and half a synonym, all
have category vectors; relevance is the category):

| Metric | Lexical BM25 | Dense Overgraph | Hybrid RRF |
| --- | ---: | ---: | ---: |
| Recall@20 | 0.50 | 0.50 | 0.50 |
| Recall@50 | **0.50** | **1.00** | **1.00** |
| NDCG@20 | 1.00 | 1.00 | 1.00 |
| p50 | 0.13 ms | 0.71 ms | 3.25 ms |
| p95 | 0.18 ms | 0.85 ms | 3.46 ms |

This is a **synthetic** lexical-vs-dense check, not a production golden set. It
shows the expected reason to keep a lexical strategy: exact/synonym coverage
differs; it does not establish general search quality.

Index mechanics:

| Measurement | Value |
| --- | ---: |
| Full build, 200 facts | 0.56 s |
| Index size | 52 KB |
| Incremental reconcile, 20 new facts | 0.55 s |
| Manual delete of one key | 0.026 s |
| Process max RSS at end | 405 MB |

The 0.55 s reconcile is dominated by Tantivy writer startup for this tiny
corpus, not by the 20 documents. It must be measured on a real corpus before
drawing conclusions.

Co-located owner simulation (owner + four Tantivy search threads in the same
process): mutation p50 5.10 → 5.85 ms, p95 6.02 → 7.49 ms, p99 6.51 → 9.03 ms.
This is a CPU-contention simulation, not proof of owner-event-loop impact; the
real B integration must run searches on the owner read executor and repeat the
mixed workload.

## Findings that block a strategy decision

1. **Deletion is broken/missing.** `reconcile` leaves deleted documents in the
   index; the benchmark shows the stale key still returned, and only the manual
   `delete_keys` removes it. Ingest/re-ingest/delete/revoked-anchor behavior
   needs a first-class tombstone or generation model before any shared index.
2. **No generation token.** The watermark is at-least-once for updates but does
   not prove the index is complete after deletes, failed reconciles or owner
   restart. A deterministic rebuild check is needed.
3. **Owner mode has no index integration yet.** Today the owner disables the
   index; adding B means indexing/search scheduling inside the owner and a
   deletion/reconcile lifecycle.
4. **The synthetic corpus is not a retrieval-quality benchmark.** Before
   choosing A/B/C/D, rerun on actual documents and golden questions.

## Preliminary direction

Option B (Tantivy in the owner process, searches on the read executor) is
feasible and consistent with "one derived index per catalog", but it should not
be implemented until the deletion/generation model and a real-corpus benchmark
exist. Option D remains credible for dense retrieval but would lose the lexical
coverage demonstrated above; it cannot be decided on the synthetic set.
