# Search generation write-path inventory (ticket 46)

Status: inventory before implementation. No production code changed.

The generation may only be trusted if **every** path that changes searchable
TextUnits or active anchor membership updates it in the same atomic write. One
missed path makes stale snapshots look current.

## Inventory: searchable TextUnits

| Path | Entry point | Notes |
| --- | --- | --- |
| Canonical ingest | `knowledge/persistence.py` → `overgraph/text_units.upsert_text_units` | main document ingest |
| Batch graph ingest | `overgraph/ingest.py` → `write.upsert_text_unit` | batch writes |
| Domain TextUnit upsert | `overgraph/write.upsert_text_unit` | core node + CONTAINS edge |
| TextUnit deletion / re-ingest | `knowledge/persistence.delete_text_units_for_document` | must bump before/with delete |
| Backfill | `knowledge/backfill_text_units.py` | background repair |
| Research-added units | `overgraph/research.add_text_unit_ref` / unit upsert | research path |
| Segmentation changes | `knowledge/segmentation.py` + persistence callers | changed unit set |
| Chunk/embedding updates | `knowledge/vector_store.py` callers | embedding change must invalidate |
| Canonical ingest catch-up | `knowledge/canonical_ingest.py` | partial re-ingest |
| Other call sites | `grep -rn "upsert_text_unit\|delete_text_units_for_document"` | inventory all before wiring |

## Inventory: active anchors

| Path | Entry point |
| --- | --- |
| Promote | `clause_ssr/anchors.promote_anchor` |
| Revoke anchor | `clause_ssr/anchors.revoke_anchor` |
| Revoke verification cascade | `clause_ssr/verifications.revoke_verification` |
| Stale embedding | `clause_ssr/anchors.mark_stale_embeddings` |
| Anchor set build/rebuild | `clause_ssr/select.build_anchor_set` |
| Admin anchor operations | `/clause-ssr` anchors/promote/revoke endpoints |
| Background repair | any anchor backfill/reconcile job |

## Required shape

```python
def mutate_searchable(catalog, scope, change):
    txn = catalog.begin_write_txn()
    try:
        generation = read_generation(txn, scope)
        change(txn)                      # actual TextUnit/anchor writes
        txn.upsert_node(..., generation + 1)  # same txn
        txn.commit()
    finally:
        if not committed:
            txn.rollback()
```

Callers must not update the generation separately. If a write path cannot use
the transaction yet, it must be converted before the generation is used for
validation.

## Concurrency and publication

- Two concurrent mutations must produce two distinct generation increments; a
  lost update fails the test.
- Aborted mutation: neither data change nor generation change visible.
- Snapshot stores G1/G2; before/after check; bounded retry; if retry races,
  store as historical.
- “Current” is derived by comparing snapshot generations with authoritative
  state at read time, never a permanent flag written at publish time.
- Define the snapshot’s linearization point as the atomic generation read/commit
  boundary; document it in the snapshot row.

## Acceptance tests

1. Parallel TextUnit writes: both changes visible, generation increases twice.
2. Parallel anchor revocation/promotion: same.
3. Aborted mutation leaves both data and generation unchanged.
4. A snapshot computed with G1 cannot be presented as current after G2 != G1.
5. Cache hit validates current generations; validation error recomputes.
6. Inventory check: a test fails if a new `upsert_text_unit`/`revoke_anchor`
   call site is not routed through the common mutation wrapper.
