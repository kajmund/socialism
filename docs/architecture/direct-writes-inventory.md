# Remaining direct graph writers: inventory and runtime guard

Status: inventory + runtime guard. No direct-writer migration is enabled in this
slice. PR #432 stays open and `write_paths_ready=false`.

## Inventory

| Area | Catalog used | Production callers | Status |
| --- | --- | --- | --- |
| Legal claims/evidence (production paths) | **Owner knowledge catalog** | claim persistence, evidence, claim answers, supersession | **migrated** through `owner_legal.py`; atomic claim+evidence+supports batch and owner reads. Offline backfill/parity/rekey tooling still uses direct catalog |
| Document QA (`document_qa/store.py`, `catalog_write.py`, `review.py`, `lifecycle.py`) | **tenant Knowledge Owner** | graph writeback worker, workspace tools | **migrated**: catalog ingest, type index, Q&A writeback, reuse and `find_documents` use the tenant Owner and fail explicitly without a route. Direct modules are test/offline only and are lazily imported; `TenantCatalogs` is offline/benchmark only. | Cutover is blocked on tenant Knowledge Owner lifecycle/routing; separate catalog per tenant needs its own Owner instance |
| mem0 (`overgraph/mem0_store.py`) | **memory catalog** (`root/memory`) | expert memory through mem0 | **owner repository ready, adapter not switched**: `owner_memory.py` provides owner-backed upsert/get/update/delete/search/list/link with two tests, and `OVERGRAPH_MEMORY_OWNER_SOCKET` configures its route. A mem0 **staging** vector store (`memory_staging.py`) lets one extraction run in memory and publish its diff through `owner_memory.apply_changes`, so no synchronous Owner calls are needed. With `OVERGRAPH_MEMORY_OWNER_SOCKET`, `OwnerExpertMemory` is the expert-memory factory; the legacy mem0 adapter remains only when the memory route is unset. |
| SWE run store (`overgraph/workflows.py`) | separate workflow/run-store catalog | SWE workflows | **do not migrate here**; it is not the Owner knowledge catalog |
| Jev cache (`overgraph/jev_cache.py`) | separate cache store | Jev cache | **do not migrate here**; separate cache store |
| Graph v2 worker (`graph_v2/outbox.py`, `worker.py`) | owner knowledge + tenant Owners | backend graph loop | **owner mode enabled**: document kinds use tenant Owners; legal projection uses the Knowledge Owner (`owner_legal_writeback.py`). Legacy direct path only when Owner runtime is not configured. Tenant acceptance is in `verify_owner_multiprocess_fastapi.py`. |
| Backfill/parity/offline maintenance | knowledge/tenant files | offline scripts | explicit maintenance paths, not request-time writers |

The static writer allowlist still lists these modules. A static allowlist alone
is not evidence that owner mode is safe: dynamic paths can open a tenant catalog
or the memory catalog without going through the knowledge Owner.

## Runtime guard

Legal production writes now go through `owner_legal.py` on the existing
Knowledge Owner. `Catalog.set_direct_writes_forbidden(True)` is set by the
backend lifespan in owner mode. Every knowledge-catalog write entry point (`upsert_node`,
`batch_upsert_nodes`, `upsert_edge`, `graph_patch`, `delete_node`,
`begin_write_txn`, property index, ingest mode) raises `DirectWriteForbidden`
instead of silently writing locally. The owner process itself never sets this
flag. Memory-catalog writes remain allowed until a memory Owner exists.

This guard is intentionally runtime-level: it catches dynamic call paths that a
static inventory misses. Tests cover knowledge-write rejection and memory-write
allowance.

## Why no migration landed in this slice

- **Document QA** uses per-tenant catalogs, not the single knowledge catalog.
  Migrating it means running/owning one Owner per tenant catalog and changing
  `TenantCatalogs` lifecycle/locking. That is an architecture decision, not a
  call-site rewrite.
- **mem0** writes the separate memory catalog. It needs a memory-catalog Owner
  (or a documented decision that memory remains local); reusing the knowledge
  Owner would mix two catalog kinds.
- **Legal claims/evidence** production paths are migrated: claim/evidence/
  support publication is one Owner batch; claim identity, evidence links,
  support validity, answers and supersession go through Owner reads. Offline
  maintenance tools (backfill, parity, rekey) still use direct catalogs and are
  not request-time paths.
- **SWE run store / Jev cache** are separate derived stores and should not be
  migrated merely because they embed Overgraph.

No half migration was left in place. The next implementation should choose the
per-catalog Owner model for tenant/memory catalogs and convert legal claim
reads+writes together.

## Runtime acceptance before `write_paths_ready=true`

1. Start Owner + real backends with local knowledge writes forbidden.
2. Exercise document QA, legal claim/evidence, mem0 and SWE paths dynamically.
3. Assert no local knowledge/memory write succeeds outside an Owner.
4. Only then set `write_paths_ready=true`; static allowlist absence is not enough.
