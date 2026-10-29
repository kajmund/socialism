# Tabular Review result snapshots and review history

Status: design decision for ticket 45. No production schema or behaviour has
changed yet. PR #430 remains experimental.

## Three data types

| Data | Store | Validity |
| --- | --- | --- |
| Verified anchors + TextUnit embeddings | Overgraph | Authoritative, versioned |
| SSR Top-K match result | Derived snapshot | Valid only against a current fingerprint |
| User approval / lock / history | Persistent review history | Preserved even when the SSR snapshot becomes historical |

A locked cell means the user locked their review decision. It does **not** mean
the underlying SSR match is valid forever.

## Snapshot

A review row/column points at a result snapshot, not directly at the current
match:

```text
TabularReviewCell
  review state · lock · history · result_snapshot_id
        │
        ▼
TabularReviewResultSnapshot
  top-K · scores · source references · fingerprint · computed_at
```

The snapshot is compact: the existing Top-K rows plus one fingerprint. It is a
derived result, not knowledge. It can always be recreated from Overgraph.

A new `tabular_review_result_snapshots` table in the existing SQL database is
acceptable; this is not a new datastore. No Redis, no separate vector database.

## Fingerprint

The fingerprint must cover every dependency:

- tenant / customer scope
- deterministic revision of the actual searchable TextUnit set
  (unit ids + content hashes, not only document_version_id; partial re-ingest
  and changed segmentation must change it)
- AnchorSet id, version and authoritative membership revision
- embedding model/revision
- category/label, polarity, threshold, candidate limit
- algorithm version

The fingerprint must be checked against authoritative Overgraph state. A
matching cached fingerprint never authorizes revoked anchors by itself.

## Warm path

1. Load the snapshot fingerprint and the lightweight current revision.
2. Verify tenant, units revision and authoritative anchor membership.
3. If equal, reuse Top-K.
4. If different or verification fails, recompute (same as D) and replace the
   snapshot. Never present a stale snapshot as current.
5. Locked cells keep their review history; mark the referenced snapshot as
   historical when the fingerprint no longer matches.

A technical failure during validity checking must be treated as stale and
recomputed, never as valid.

## Cost

Fingerprint validation must be cheap. Ideally Overgraph exposes an atomic
generation/revision for the searchable unit set and anchor membership. Reading
thousands of TextUnits on every warm request would eat C's advantage. Measure
fingerprint validation separately; 30–50 ms with correct invalidation is
preferable to 14 ms with stale results (illustrative, not a new target).

## Adoption gates

- Unchanged inputs: C reuses Top-K and keeps the fast warm path.
- Changed document or AnchorSet: C recomputes and matches D.
- Revoked anchor: no new or reused current hit may contain it.
- Locked cell: history preserved; marked historical if inputs changed.
- Two workers / process restart: same validity decision.
- Validity-check failure: no stale reuse.
- Top-1/3/5 and scores equal to D before and after invalidation.
- Revocation tested warm and after a cache miss.

No SSR scoring, threshold or Jev changes are part of this work.
