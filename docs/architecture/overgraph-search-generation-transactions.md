# Search generation transaction model

Status: verification before ticket 46 implementation. No production change.

## What Overgraph actually guarantees

- `graph_patch` is one atomic operation: upsert nodes/edges, delete nodes/edges
  and invalidate edges all commit or none. It is exposed as
  `Catalog.graph_patch`.
- `begin_write_txn()` / `WriteTxn` supports reads and writes in one native
  Overgraph transaction with optimistic conflict detection. A conflicting
  commit fails and must be retried.
- Writes are single-writer; there is no MVCC snapshot isolation and no
  cross-process host lock guarantee.

Consequence: **do not build a second transaction engine.** Use native
`WriteTxn` for read-modify-write of the generation, and `graph_patch` only for
batches that do not need a read-modify-write condition.

## Why graph_patch alone is not enough for the counter

A generation bump is:

```text
read generation -> write generation + 1
```

Two concurrent `graph_patch` calls can both read 184 and write 185, losing one
update. `graph_patch` is atomic but not conditional. The native `WriteTxn` with
optimistic conflict detection is the correct primitive; on conflict, retry the
whole read-modify-write.

`mutate_searchable` therefore wraps a native `WriteTxn`, not a new abstraction.
TextUnit/anchor writes and the generation node go into the same transaction.

## No-op matrix

| Mutation | Bump? |
| --- | --- |
| New TextUnit | yes |
| Changed text/content hash/searchable embedding/metadata | yes |
| Identical upsert | no |
| Delete existing TextUnit | yes |
| Delete missing TextUnit | no |
| Revoke active anchor | yes |
| Revoke already-inactive anchor | no |
| Irrelevant audit metadata | no |

Generation represents a change in the possible search result set, not write
attempts. Compare current and desired state inside the transaction before
deciding whether to bump.

## Scope and future

Start with one generation per tenant/scope for simplicity. Structure the key so
document- or collection-scoped generations can be added later. Measure how often
scope-wide invalidation is unnecessarily broad before changing the key.

## Bootstrap

- On activation, existing TextUnits and active anchors get a valid initial
  generation in one bootstrap write.
- Old snapshots without a generation fingerprint are invalid.
- If generation validation cannot establish authority, fail closed: do not
  present the snapshot as current. Recompute; if the post-recompute check also
  fails, store as historical, never current.

## Extended acceptance

1. All 32 write paths covered.
2. Atomic read-modify-write via native WriteTxn; no lost update under parallel
   writers.
3. No-op/idempotent ingest does not bump the generation.
4. Bootstrap of existing content; old snapshots invalid.
5. Fail-closed validation; cache errors are distinct from authority errors.
6. Generation read benchmark, including parallel workers.
7. Linearization point documented: the WriteTxn commit that contains both the
   data change and the generation bump.

## Multiprocess probe (2026-10-24)

A two-process probe was run against the same local Overgraph catalog:

- Two processes opened the same catalog and, when staggered, both wrote
  different nodes; both nodes were readable afterwards.
- Concurrent generation read-modify-write: both processes read generation 0,
  both attempted to write 1; the final value was 1 (one update lost) and one
  process hit an I/O error while closing.

This is **not** evidence of safe multiprocess writes. It confirms the documented
model: single writer, optimistic conflict detection only inside the supported
writer, and no cross-process host lock.

### Consequence

- Do not enable generation-based invalidation while multiple backend processes
  can write the same Overgraph catalog.
- Prefer one dedicated writer/owner per catalog; route graph mutations through
  it. Readers may remain parallel only after visibility semantics are verified.
- Within the writer process, native `WriteTxn` conflict retry handles concurrent
  tasks.
- One atomic batch (many TextUnits) gets **one** generation bump, not one bump
  per unit.
- No distributed lock is introduced until a single-writer arrangement is proven
  insufficient.

### Required tests before use

1. In-process concurrent writers: first commit wins, second retries, both data
   changes visible, generation increases twice.
2. Abort after data mutation before commit: neither data nor generation visible.
3. Multiprocess: supported configuration documented, or all mutations routed to
   one writer and both processes verified through it.
