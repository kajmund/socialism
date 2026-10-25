# Durable generation/tombstone ledger for the derived Tantivy index

Status: ledger is now written by the Owner's production mutation paths
(server-side `owner.py`/`owner_mutations.py`), with tests in
`backend/app/services/tantivy_generation.py` and
`backend/tests/test_tantivy_generation.py`. No Tantivy production activation
and no A/B/C/D placement choice yet.

## Inventory (reuse first)

- The Owner already has a durable generation primitive inside its existing
  batch protocol: a `generation` node with a monotonic `generation` property,
  bumped atomically with the batch (`owner.py:_apply_batch`).
- Owner mutation receipts are durable but are idempotency records, not an
  ordered index cursor. `read_revision` is in-memory and is **not** used as an
  indexer cursor.
- TextUnits carry `document_version_id`/`content_hash`; document versions are
  authoritative in SQL and graph; facts carry scope/status.
- The existing Tantivy watermark is `updated_at` milliseconds, which cannot
  represent deletes and can tie; it remains for backward compatibility but is
  not the new indexing contract.
- No new Owner protocol is introduced. The ledger is written through the
  existing batch/conditional transaction path, automatically for changed
  TextUnit/Fact nodes.

## Model

Every changed TextUnit/Fact in an Owner batch or conditional mutation appends
explicit change records and bumps one monotonic generation in the **same native
transaction**. Non-search nodes (entities, receipts, clause records) do not
bump it. Explicit deletes and fact status transitions to non-active produce
delete records; failed/no-op/duplicate mutations do not:

- generation node: `SearchIndexGeneration` / `search-index:generation`
- change node: `SearchIndexChange` / `search-index:change:<generation>:<n>`
  with `{generation, op: upsert|delete, kind: text_unit|fact, key,
  scope_key, document_version_id}`

The indexer keeps a durable checkpoint file (`generation.json`) next to the
Tantivy index. It reads change records for each generation after the checkpoint,
applies deletes (`delete_keys`) and upserts (hydrated from the Owner), commits
Tantivy, and only then writes the checkpoint atomically with fsync + directory
fsync.

Properties:

- **Monotonic and durable:** generation survives Owner restart and is bumped
  atomically with changes; equal timestamps cannot merge changes.
- **Explicit deletes:** a delete is a tombstone record, not an absent upsert row.
- **At-least-once / idempotent:** replaying a generation re-applies keyed
  upsert/delete operations; a crash after Tantivy commit but before checkpoint
  safely replays.
- **Lag detection:** `SearchIndexer.lag()`/`assert_current()` compare the
  checkpoint with the current durable generation.
- **Deterministic rebuild:** `rebuild_from(catalog, index_dir, generation=...)`
  rebuilds from the current authoritative graph and resets the checkpoint.
- **No cache activation:** this is internal indexing metadata only; tickets
  45/46 remain disabled.

Missing change records or a generation above 1000 records require a rebuild;
the indexer fails closed instead of silently advancing.

## Production paths now writing the ledger

- TextUnit ingest/upsert and document re-ingest (batch upserts/deletes)
- TextUnit/document delete (`delete_nodes` batch)
- Fact write/update and fact revocation/status changes
- Clause SSR and other owner-migrated writes that create/update/delete TextUnit
  or Fact nodes
- Receipts stay in the same transaction

Still missing: direct writers outside the Owner (document QA, legal claims,
mem0, SWE run store) do not append this ledger; they are unmigrated and
`write_paths_ready` stays false. Embedding-only updates do not change lexical
search text and are intentionally not ledgered.

## Verified scenarios

`backend/tests/test_tantivy_generation.py`:

| Scenario | Result |
| --- | --- |
| TextUnit deleted | removed from Tantivy after apply |
| Re-ingest | old version absent, new version searchable |
| Indexer crash after index write, before checkpoint | restart replays idempotently, no duplicate hit |
| Owner faster than indexer | lag > 0 detected; `assert_current` raises; apply catches up |
| Checkpoint ahead of ledger | rebuild required |
| Non-search node change | generation unchanged |
| Duplicate/failed mutation | no extra generation |

## Freshness before evidence use

The generation model detects lag but does not by itself make a stale index
authoritative. For searches where current validity is mandatory, use Tantivy
only as a candidate source and verify candidates against the Owner (existence,
document version, fact status/validity) before using them as evidence. This is
the intended next wiring step; it is not enabled here.

## Performance and corpus status

The ledger adds one generation node and one change record per changed
search item, inside the existing mutation transaction. The multiprocess harness
still passes after wiring (ingest ~0.47 s, 0 direct writes). The mixed-workload
mutation benchmark and Tantivy search benchmark were measured before this
wiring; neither has been rerun against the ledger path yet.

No existing production golden retrieval set was found in the repository. The
quality numbers in the strategy note are synthetic and must not be used to
choose a placement. A real contract corpus + golden questions remains a
prerequisite.

## Remaining before choosing A/B/C/D

1. Wire ledger appends into production search-relevant write paths (document
   ingest/re-ingest/delete, fact revocation) atomically with their data changes.
2. Define change-record retention/GC and rebuild strategy when old generations
   are no longer retained.
3. Hydrate/candidate verification from the Owner for stale-index protection.
4. Run the real contract corpus with golden queries and compare A/B/C/D.
5. Decide index placement only after 1–4; no production Tantivy is enabled in
   this slice.
