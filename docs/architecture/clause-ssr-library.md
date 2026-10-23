# Clause SSR library

Isolated, opt-in library of human-verified clause examples and SSR matching.
Production research, evidence sufficiency, Jev, SWE execution, and report
tone/style SSR are unchanged.

Reuse audit: [clause-ssr-reuse-audit.md](clause-ssr-reuse-audit.md).

## What this is

Administrators label existing OverGraph **TextUnits** with binary questions
("Är det här en uppsägningsklausul?"). YES/NO become verified examples for
that question only. Skip/unsure are not labels. A YES does **not** become an
active SSR anchor until someone explicitly promotes it and builds an
`AnchorSet`.

Matching is cosine similarity against stored embeddings. Cosine 0.94 is not
94 % probability.

## Data model (OverGraph)

| Node | Meaning |
| ---- | ------- |
| `SsrClassification` | Versioned question + category + level |
| `SsrVerification` | Current human decision on a TextUnit |
| `SsrVerificationRevision` | Superseded answers (audit) |
| `SsrClauseAnchor` | Promoted example with embedding identity |
| `SsrClauseAnchorSet` | Versioned, diversity-aware selection |
| `SsrReviewSession` | Resume + undo for one reviewer/question |

Edges (namespaced, same convention as `legal.*`): `ssr.ABOUT`, `ssr.ANSWERS`,
`ssr.DERIVED_FROM`, `ssr.REPRESENTS`, `ssr.MEMBER_OF`, `ssr.FOR`,
`ssr.SUPERSEDES`.

TextUnits are reused. There is no parallel document or vector store.

## API (`/clause-ssr`, admin only)

| Method | Path | Role |
| ------ | ---- | ---- |
| GET/POST | `/classifications` | List / upsert questions |
| PATCH | `/classifications/{id}` | Activate / deactivate |
| GET | `/queue` | Prefetch next cards |
| POST | `/decisions` | Idempotent YES/NO/skip/unsure |
| POST | `/decisions/undo` | Revoke last answer |
| POST | `/anchors/promote` | Explicit draft anchor |
| GET | `/anchors` | List draft/active anchors |
| POST/GET | `/anchor-sets` | Build / list versioned sets |
| POST | `/match` | Opt-in top-k + category scores |

Scores always include `score_kind: cosine_similarity` and
`not_a_probability: true`.

## Matching

- Reuses a TextUnit `dense_vector` when model/revision/dimension match.
- Fails loud if the vector is missing. No silent embed/LLM call.
- Returns top-k anchors, category score, margin, independent support, and
  negative-example signal.
- Multi-label is allowed. Low similarity or low margin → abstain/`unknown`.
- Tenant isolation: a customer never sees another customer's anchors.

## Benchmark

`backend/tests/test_clause_ssr_benchmark.py` and
`backend/scripts/benchmark_clause_ssr.py` use **scripted fixture vectors**.
They are not live model-quality measurements. Golden clause ids are held out
of AnchorSet selection.

Reported: Precision@1 on holdout, abstention, false positives, and change
after 2 vs 4 labels. Localization ≠ value extraction: finding a price clause
does not claim the extracted price is correct.

## Limits (this delivery)

- Queue order is deterministic (document, version, ordinal). No active-learning
  sampler yet.
- Near-duplicate filter is exact `content_hash`.
- No calibration of cosine into a probability.
- No automatic promotion of model-generated labels.

## Later integration (do not do now)

Stable call for future SWE/research, behind an explicit opt-in:

```text
POST /clause-ssr/match
  { text_unit_id | dense_vector, customer_id, k }
→ top_k, category_scores, labels | abstain
```

Intended later uses (separate PRs):

1. Categorize new contracts/clauses at ingest.
2. Fast retrieval of termination, price, extension, liability clauses.
3. Candidate filter/rank before Jev.
4. B3-like fact-pair priority in research.
5. Active learning from newly verified cases.

Do **not** wire this into `swe_bridge`, evidence sufficiency, routing, Jev
gates, or report SSR until that PR exists.
