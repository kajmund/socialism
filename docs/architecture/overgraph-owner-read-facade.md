# Owner-only authoritative reads: facade, vertical integration and remaining paths

Status: first vertical slice and Phase A1 answer reuse implemented and verified
(PR #432). Companion to
[overgraph-owner-multiprocess-hardening.md](overgraph-owner-multiprocess-hardening.md)
and [overgraph-owner-answer-reuse.md](overgraph-owner-answer-reuse.md).

## Goal and model

The owner is the only process that opens the knowledge catalog for reads or
writes. Backends compute over data returned by the owner instead of holding a
their own (stale) catalog snapshot. A customer may have several catalogs; the
owner is selected before graph access. No tenant filtering is added inside the
graph domain.

In owner mode the backend:

- opens **only the memory catalog** locally; `require_knowledge()` raises
  `OwnerReadRequiredError`, mapped to HTTP 503
  `knowledge_requires_owner_read`;
- does not start the retrieval-index or graph-writeback loops (their read
  migration is Phase B/C);
- reads knowledge through the owner facade / admin read API;
- keeps `write_paths_ready` false.

Backends in non-owner mode (tests, offline tools without an owner socket) keep
the previous local runtime.

## Read protocol (existing owner socket, bounded operations)

Every operation carries the catalog id, is typed by `type`, and returns a clear
error instead of a silent empty result on transport/protocol failure.

| Operation | Contract |
| --- | --- |
| `read` | known label/key pairs; optional vectors |
| `list_nodes` | label + equality props, row cap 1000 |
| `query_nodes` | label + equality props, row cap 1000, optional vectors, stable node-id cursor (`next_cursor`), deterministic id order |
| `count_nodes` | label count only |
| `node` | node by engine id, props + optional vector + bounded outgoing/incoming edges |
| `neighbors` | direction + edge-label filter, max 200 edge entries |

Responses include `read_revision`, an in-memory monotonic counter incremented
after every applied mutation. It is not a durable generation and resets on owner
restart; it lets a client that paginates detect that the catalog changed between
pages and retry. The server records read ops, objects, bytes and latency in
owner metrics; health exposes them.

The admin API (`/overgraph/...`) uses the owner in owner mode:
`POST /overgraph/knowledge/query` (bounded, typed body), `GET nodes`,
`GET node/{id}`. The memory catalog keeps the local path until Phase D. `?q=`
text scanning is not supported in owner mode and returns 400 rather than a
silent fallback.

## First vertical integration (verified)

`backend/scripts/verify_owner_multiprocess_fastapi.py` starts real owner + two
real uvicorn backends. Backend A ingests a document; backend B then reads
TextUnits **with embeddings** through its own HTTP API
(`/overgraph/knowledge/query`), and:

| Check | Result |
| --- | --- |
| B never opens the knowledge catalog locally | guard log 0 entries (`OWNER_TEST_NO_LOCAL_KNOWLEDGE=1`) |
| A writes, B reads TextUnits + vectors for A's document version | pass |
| Document id / version / TextUnit props / embeddings | pass |
| Update (new clause decision) and revoke (undo) visible from B | pass |
| Owner restart, no backend restart; B still reads current data | pass |
| Wrong catalog id / owner loss | clear 502/503, no fallback |
| No direct `Catalog` writes in either backend | 0 attempts |
| End-to-end ingest (upload threads + job + vectors) | 0.45–0.56 s wall |

`backend/tests/test_overgraph_owner_read_facade.py` covers bounded queries,
pagination, vectors, node/edge detail and the owner-mode startup path (only the
memory catalog is opened). The old stale-snapshot implementation had no owner
read path, so both this test and the two-backend harness fail on it.

## Read-path inventory and status

| Path | Classification | Status |
| --- | --- | --- |
| `/overgraph` admin graph reads | bounded owner query | **migrated** |
| ingest/embedding/reuse post-write TextUnit readbacks | read-after-write | **migrated** (owner `list_nodes` helper) |
| document deletion TextUnit/evidence resolution | read-after-write | **migrated** |
| research fact writer endpoint/provenance reads | read-after-write | **migrated** (owner key reads) |
| research answer reuse (`answer_facts`, `current_fact`, `entity_attributes`) | authoritative | **migrated** (Phase A1) |
| research graph reuse / candidate retrieval / hybrid search | bounded retrieval | **not migrated** |
| Tantivy index build/reconcile | snapshot/index build | **not migrated**; owner mode disables it |
| clause SSR queue/match/classifications/anchor reads | authoritative | **not migrated**; write paths already owner |
| Tabular Review snapshots/search | bounded retrieval | **not migrated** |
| document navigation / document properties | authoritative | **not migrated** |
| document QA catalog apply/outbox | read-after-write | **not migrated** |
| legal claims/evidence reads | authoritative | **not migrated** |
| memory / mem0 | authoritative | **not migrated**; still local memory catalog |
| tenant catalog routing (`document_qa/tenants.py`) | separate catalogs | **not migrated**; Phase D |

Owner mode fails closed for the unmigrated paths; it never returns stale local
data.

## Tantivy decision (Phase B, not implemented)

Two options are on the table and need measurement before choosing:

1. paginated bounded owner reads to rebuild/reconcile the derived index;
2. a bounded owner change/revision feed for incremental updates.

No general change-stream is added before that measurement. Until then owner mode
disables the index and surfaces it in health/logs rather than serving a stale
index.

## Performance (owner process + real Unix socket, 3 000 TextUnits)

`backend/scripts/benchmark_owner_reads.py`

| Read | Owner p50/p95 | Local catalog p50/p95 | Avg response |
| --- | ---: | ---: | ---: |
| 1 node | 0.24 / 0.47 ms | 0.01 / 0.15 ms | 0.3 KB |
| 100 nodes | 0.94 / 1.08 ms | 0.40 / 0.67 ms | 24 KB |
| 1 000 nodes | 7.86 / 9.01 ms | 4.32 / 4.86 ms | 246 KB |
| node by id (50) | ~0.3 ms | — | — |
| count | ~0.7 ms | — | — |

Concurrent bounded queries: 1 client 832 q/s, 8 clients 1 340 q/s, 32 clients
1 324 q/s, 100 clients 1 288 q/s. Under load from 8 reader loops, mutation p50
went from ~0.5 ms to ~4.6 ms (sync off in this benchmark); the facade is bounded
and does not serialize the graph, but reads and writes share the owner event
loop. Large result sets remain the client's explicit choice.

## Remaining work / blockers

1. Migrate the remaining Phase A retrieval reads (graph reuse, candidate
   retrieval, hybrid/vector search). Known-answer reuse is already migrated; it
   performs four bounded owner reads and carries 3.2/8.5/62 KB for 1/10/100
   evidence items (see the answer-reuse note).
2. Decide and implement Tantivy consistency (bounded paging vs bounded change
   feed) after measuring both.
3. Migrate Phase C clause/Tabular reads and Phase D document QA/legal/memory.
4. Add a committed SQL-connection probe with the separate Phase D boundary work.
5. The static opener guard is a first step; once all paths are migrated, remove
   the `document_qa/tenants.py` etc. exceptions.
6. `write_paths_ready` stays false; tickets 45/46 stay blocked.
