# Tabular Review cache experiment (A/B/C)

Status: isolated experiment design, not a production change. PR #430 remains the
baseline harness.

## Hypothesis

The full TextUnit × column score grid (2 377 × 4 = 9 508 rows for the first
corpus) is not needed to answer Tabular Review. The useful result is the best
clauses per document/category. Persisting only Top-K candidates per
document/category should cut most cache-row construction and persistence
without changing the selected clauses.

## Arms

| Arm | Scoring | Persistence |
| --- | --- | --- |
| A | Current per-unit loop | Full grid + cell candidates (baseline) |
| B | Same scoring as A | Top-K result persistence only |
| C | Vectorized batch scoring (numpy) | Top-K result persistence only |

All arms use exactly the same ingested documents, document versions, TextUnit
embeddings, anchor sets, thresholds and candidate limit. No Jev, no new LLM
calls, no new datastore (no Redis, no separate vector DB).

## Measurements

For 35 documents × 4 columns, cold and warm:

- time to first usable row (backend and UI paint separately)
- time to complete table
- add a fifth/new category column
- score time, cache-row construction, persist time, Overgraph load time
- persisted row count vs 9 508 baseline
- cache hit rate; result-cache invalidation on anchor revoke/revision

Targets are hypotheses: cold < 2 s, warm ≤ 0.62 s, new column < 1 s.

## Equality gates

Compare A/B/C per document/category:

1. Top-1, Top-3 and Top-5 text units are identical, including stable
   tie-breaking by text_unit_id.
2. Similarity is equal within a documented numeric tolerance.
3. Negative anchors and abstention behave identically.
4. No result above the threshold disappears.
5. Revoked anchors produce no new matches; lock/review history is unchanged.
6. A lowered score threshold never treats a cached Top-5 list as the whole
   candidate space: a new search is required.

## Two caches, separate rules

- **Embedding cache:** TextUnit vectors already in Overgraph, content-addressed
  and embedding-model-versioned. Verification/revocation never recomputes them.
- **Result cache:** Top-K hits per document version, category and AnchorSet
  revision. Anchor promotion/revocation changes the revision and invalidates
  only this layer.

## Decision rule

Do not change production cache behaviour unless A/B/C produce identical
clauses and the measured cold/new-column gains hold. Any cache redesign that
changes Top-K or threshold semantics is rejected regardless of speed.
