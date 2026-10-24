# Owner multiprocess hardening: real backends, restart, durability

Status: verification + hardening note (PR #432). Companion to
[overgraph-research-fact-writer.md](overgraph-research-fact-writer.md).

## What was verified against the real stack

`backend/scripts/verify_owner_multiprocess_fastapi.py` starts four real OS
processes: a separate owner, and the actual FastAPI app under uvicorn twice
(`scripts/owner_test_backend.py`). Both backends share one SQLite database and
one Overgraph catalog and are wired to the same owner catalog id. The backend
processes install a guard that records any direct `Catalog` write attempt; the
only replaced boundaries are object storage (shared filesystem store) and the
OpenAI embedding call (deterministic fake). The API, ingest job, SQL
persistence, graph writes and owner socket are real.

Run it (from `backend/`, needs the built `swe_native` like the test suite):

```bash
.venv/bin/python scripts/verify_owner_multiprocess_fastapi.py --json /tmp/owner_mp.json
.venv/bin/python scripts/benchmark_owner_hardening.py --json /tmp/owner_bench.json
```

Result on the current branch (repeatable):

| Check | Result |
| --- | --- |
| Both backends ready, same `catalog_id` as owner | pass |
| `write_paths_ready` stays false | pass |
| No direct `Catalog` write attempt in either backend | 0 attempts |
| Concurrent document ingest through both HTTP APIs | both `ready`, 1 TextUnit + 1 vector each |
| Owner-read back after ingest | 2 TextUnits, 2 vectors, 2 DocumentVersions, 2 CONTAINS |
| Concurrent clause decisions through both HTTP APIs | 4 verifications, 1 review session, all 4 API calls 200 |
| Wrong `OVERGRAPH_OWNER_CATALOG_ID` | health `unavailable`, ingest job fails, no direct write |
| Backend starts before owner | `unavailable`; after owner start health `ready`; ingest succeeds |
| Owner stops mid-work | health `unavailable`, ingest fails loudly, no fallback; restart → ready → ingest succeeds |
| Two owners on one catalog | second process exits non-zero (`already owned`) |
| Acked mutation, owner SIGKILL immediately after ack | recovered after restart (`sync_on_commit=True`) |
| Facts/evidence through a backend HTTP API | not exercised end-to-end (no deterministic LLM-free fact endpoint); covered by owner unit/differential tests |
| Same id+payload replay after restart | `duplicate: true`, one node |
| Owner read after write | current |
| Backend-local catalog read after owner write | **stale snapshot** (see below) |

## Critical finding: backend-local catalog reads are stale

OverGraph 0.17.0 loads the WAL/segments when a handle is opened and is not
cache-coherent between processes. A catalog opened in the backend before an
owner commit never sees that commit, even after the owner `sync()`; reopen sees
it. Probes reproduced the documented multi-process-open breakage (segment
rename failure, stale manifest visibility). The test suite had masked this
because its owner fixture wraps the same in-process `Catalog` object.

Consequences and fixes in this change:

- `materialized_document.persisted_segment` and the embedding input loader now
  read post-write TextUnits through the owner
  (`owner_writer.load_text_units_via_owner`, using the existing
  `list_nodes(label, props=...)` verb). Without this, ingest returned
  `chunks_indexed=0` and embeddings were silently never written in a real
  deployment.
- `canonical_ingest.persist_extracted_source` reuse probe uses the same owner
  read; otherwise a healthy current version looked empty and was superseded.
- Document deletion now resolves TextUnit ids and evidence-link keys through the
  owner before the atomic delete; the local snapshot used to produce an empty
  delete set and could orphan the whole document graph.
- `owner_client.list_nodes`/`read` now fail loudly on `ok:false` instead of
  returning an empty list.

Still stale and **not** fixed here (they need an explicit read-routing decision,
not a write migration): retrieval/Tantivy index reconciliation, document QA
catalog apply/outbox, lagen.nu post-ingest unit loads, research answer reuse
lookups, clause SSR queue after a decision, document navigation/tabular review
reads, and the unmigrated local writers (legal writeback, claims). A backend
cannot treat its locally opened catalog as authoritative while a separate owner
writes. This is the main blocker before `write_paths_ready=true`.

## Durability

Measured on OverGraph 0.17.0 (`wal_sync_mode="group_commit"`), macOS/APFS:

| Guarantee | Result |
| --- | --- |
| Atomic `WriteTxn.commit` / `graph_patch` | one WAL batch + memtable together; rollback/conflict tested |
| Visible in owner after commit | yes (memtable first) |
| Recovered after owner restart | only after WAL reached the file: timer ~50 ms, `sync()`, `flush()` or `close()` |
| Acked mutation survives SIGKILL | with `sync_on_commit=True`: 30/30; without: 29/30 in the committed benchmark run (varies with the 50 ms timer/8 KiB WAL buffering) |
| Payload size effect | WAL is userspace-buffered (~8 KiB); small commits can be lost before the timer |
| Power-loss durability | **not proven here**; only vendor fsync contract (macOS `fsync` is not `F_FULLFSYNC`) |

Integration kept minimal and configurable: one choke point in the owner worker
syncs before the response is released; `--sync/--no-sync` selects durable or
fast mode; the CLI closes the owner on SIGTERM/SIGINT. Sync runs for duplicate
acks too, because the original sync may have failed after its commit (a retry
would otherwise be acked without fsync).

Measured sync cost (in-process owner process, real socket):

| nodes/commit | commit p50 | sync p50 | sync p95 | commit+sync p50 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.048 ms | 4.38 ms | 7.34 ms | 4.43 ms |
| 100 | 0.63 ms | 4.69 ms | 5.18 ms | 5.35 ms |
| 1000 | 4.89 ms | 4.95 ms | 5.86 ms | 9.98 ms |

Owner A/B over 150 mutations: without sync 2,523 mutations/s (p50 0.33 ms), with
sync 197/s (p50 5.07 ms): +4.7 ms per ack. Large batches amortize this; small
mutations are fsync-bound. `flush()` (62–66 ms) is never used per commit.

Durable ack means *acked writes survive process crash*. Reads can observe a
commit a few milliseconds before its fsync completes, so "read returned ⇒
durable" is not claimed.

## Restart / retry / exclusivity

- Backend before owner: runtime keeps a configured client, health reports
  `unavailable`, first writes fail loudly; when the owner appears, health
  refreshes to `ready` and writes work without a backend restart.
- Owner restart on the same socket: client reconnects per request; no failover
  layer.
- Transport retry replays the identical mutation id + payload
  (`mutate_with_retry`); the receipt returns `duplicate:true` after an owner
  restart and nothing is written twice.
- A precondition conflict is a *new* merge attempt with a new mutation id.
- `flock` rejects a second owner process while one owns the catalog.
- Measured restart: ~0.5 s from stop to health-ready; first write 7 ms.

## CONTRADICTS

Fact↔Fact `CONTRADICTS` is undirected, but the direct writer used engine-id
order and the owner used writer order; the differential test hid this by
normalizing direction. Both writers now use one canonical key-sorted
orientation, and the differential test compares the edge directed. Claim-level
`CONTRADICTS` (legal-claims merge/mirroring) remains directed and unchanged;
no production caller passes `contradiction_key` today.

## SQL connection held over owner I/O

Measured (SQLite file engine, explicit pool, same technique as
`tests/test_research_connection_release.py`):

These numbers came from an ad-hoc one-connection-pool probe during the
investigation; they are not produced by a committed script yet. A reproducible
probe belongs with the Phase D fix.
- `publish_answer`: 2 owner RPCs per publication; `pool.checkedout()==1` during
  every RPC; RPC p50 0.78 ms / p95 1.16 ms; publish p50 2.34 ms.
- `persist_decomposition`: 2 RPCs, p50 1.24 ms; connection checked out
  throughout.
- Single-connection pool: a second session timed out after ~203 ms while an
  owner RPC was pending.
- 8 concurrent publications, pool 4+2: max checkedout 6; all succeed when RPCs
  are fast; with 400 ms/RPC and 0.5 s pool timeout, 2/8 timed out.

This violates the "release DB connections before external calls" rule. A safe
fix needs the freeze/decomposition callers to end their SQL transaction before
the owner segment. An attempted local commit inside `publish_answer` broke
callers that wrap the freeze in one `session.begin()` transaction and was
reverted. Recommended follow-up: pass the already-materialized frozen flag into
`publish_answer` and commit at the `capture_answer_reviews` boundary; commit the
lineage row before `link_decomposition`. Ingest (`persist_segmented_document`)
has the same pre-existing pattern around the TextUnit owner write.

## Benchmarks (real owner process, real socket)

| Metric | Durable mode | No-sync mode |
| --- | ---: | ---: |
| RPC p50/p95, 1 node | 5.4 / 6.7 ms | 0.59 / 1.29 ms |
| RPC p50/p95, 100 nodes | 7.9 / 8.4 ms | 2.8 / 5.3 ms |
| RPC p50/p95, 1000 nodes | 29.5 / 35.8 ms | 23.9 / 27.5 ms |
| Queue wait p50/p95 | 0.04 / 0.16 ms | 0.04 / 0.18 ms |
| Commit p50/p95 | 0.85 / 10.3 ms | 0.82 / 10.0 ms |
| Sync p50/p95 | 4.84 / 5.81 ms | — |
| 16 clients × 25 synthetic TextUnit mutations | 165 mutations/s, p95 111 ms | not run |
| 16 concurrent synthetic fact writes | 88 ms total, p50 49 ms | not run |
| Restart → ready / first write | 0.596 s / 6.7 ms | — |
| Durability SIGKILL, 30 acked mutations | 30/30 recovered | 29/30 recovered |

The batch/concurrency rows above are synthetic owner-client calls, not the
application's TextUnit writer or a research freeze. The real application flow is
measured separately by the harness: one document ingest per backend concurrently,
end-to-end through job completion and owner-visible vectors, took 0.485 s wall
(0.241 s to accept both uploads).

## Remaining risks / before merge

1. **Authoritative reads**: backends still open the catalog locally. Every
   authoritative read after an owner write must go through the owner (or the
   backend must not open the catalog at all). The list above is a P0 for
   `write_paths_ready=true`; the ingest/embedding readbacks are fixed here.
2. **Durability**: durable ack is proven for process crash, not power loss.
3. **SQL connection**: measured violation; caller-boundary fix proposed, not
   implemented because it changes freeze transaction ownership.
4. **Read-before-durable**: reads can see a commit before its fsync; only acks
   are durable.
5. Sync-per-ack caps single-owner throughput at ~200 small mutations/s; batched
   queue-drain sync is the next optimization if needed.
6. Multi-process open of the same catalog is unsupported; any remaining backend
   local catalog handle is therefore also a correctness risk, not just a stale
   read risk.
