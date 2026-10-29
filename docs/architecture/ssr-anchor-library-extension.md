# SSR anchor library extension for verified topic anchors

Status: implementation plan for ticket 34. No production change in this step.

## Why

The sufficiency experiments need a human-verified topic signal for candidate
generation and ranking: two clauses can be about the same subject
(`termination_notice`) while sharing almost no wording. Embedding similarity
between the two clauses alone proved a poor proxy. The anchor library must stay
one shared capability, not a second SSR system for research.

## Inventory and reuse-vs-new matrix

| Need | Existing counterpart | Decision |
| --- | --- | --- |
| Anchor set, version, status, publish gate | `ssr_anchor_sets`, `ssr_anchor_pool_items`, `api/anchor_sets.py`, admin SSR page | Reuse and extend the fixed kinds; do not duplicate storage/UI |
| Human calibration labels | `ssr_anchor_calibration_items` | Reuse for anchor-set calibration; add explicit verification records for clause decisions |
| Tone/style scoring | `app/services/ssr` (embeddings, cosine, PMF) | Reuse embeddings/cosine primitives; add per-kind classification rules |
| Verified who/when/category | not present | New Postgres verification record (authoritative) |
| Searchable anchor index | Overgraph knowledge catalog exists, but no anchor index/sync | New anchor nodes/relations plus idempotent sync; do not put anchors only in Postgres |
| Admin verification flow | existing anchor-set admin and pool-item "add as anchor" | Extend with kind-aware Ja/Nej/Osäker verification and a separate activation step |

No Cursor implementation of a clause/topic anchor library or Overgraph anchor
index was found in this checkout or its remote branches/worktrees. The Slack
thread is not accessible from this environment; its branch/commit must be
checked before implementation to avoid duplication.

## Architecture

One library, several **kinds** of anchor set:

```
SSR Anchor Library
  ├── tone
  ├── style
  ├── document_type
  ├── clause_category      # termination_notice, price, automatic_renewal
  ├── clause_variant
  └── question_intent
```

All kinds share storage, versioning, verification, activation and scoring;
classification rules are per kind.

**Postgres owns verification decisions.**

- `ssr_anchor_sets` remains the versioned set (kind, locale, labels,
  statements, status, publish gate).
- A verification record stores: anchor set/version, category label, clause text,
  verdict `yes|no|unsure`, source/provenance, verified-by, verified-at,
  activation state.
- Only verified `yes` anchors may be activated; a revoked verification
  deactivates the anchor. An activation is a separate controlled step after
  verification, never implicit.

**Overgraph owns the searchable index.**

- Active anchors become anchor nodes with category, polarity, embedding model
  version, embedding vector and relations to source TextUnits/categories.
- An idempotent sync applies Postgres changes (create/revoke/version bump) and
  records the synced revision. Failures are visible; there is no silent
  fallback to a different index.
- Matching reads the index; it returns a label and similarity plus an
  abstention when no verified anchor clears the threshold. No Jev or narrative
  LLM runs during matching.

## Vertical acceptance test (before ticket 27)

1. An administrator selects a termination clause and answers Ja/Nej/Osäker;
   Postgres stores the verification with source and provenance.
2. A separate activation step makes the verified anchor active and syncs it to
   the Overgraph index.
3. A previously unseen contract is matched against active anchors; the result
   contains category, similarity score and abstention when below threshold.
4. No Jev call is made for the match; the embedding model version is recorded.
5. A revoked verification removes the anchor from matching.

## Implementation tickets

- 35: schema + verification API (Postgres authoritative), kind-aware anchor
  payload validation, tests.
- 36: Overgraph anchor index + idempotent sync, model-version handling,
  activation/revocation, tests.
- 37: admin verification + activation vertical flow, reuse existing SSR admin.
- 38: clause matching endpoint/service with abstention; vertical test on unseen
  contracts; then ticket 27 (D comparison).

## Open decisions

- Whether the existing publish gate (calibration accuracy) applies to
  clause-category sets or only tone/style; a clause set may need a different
  verification gate.
- Which Overgraph node/relation schema and transaction boundary to use for
  activation; one activation must not leave an active Postgres row without an
  index entry.
- Embedding model/version pinning for anchors and TextUnits; mixed versions
  must fail loudly.
