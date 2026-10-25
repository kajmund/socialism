# Catalog ownership and routing

Status: architecture decision recorded; legal claims migration is the first
implementation slice. No Tantivy placement or ticket 45/46 work.

## Decision

Every active Overgraph catalog is owned by exactly one logical Owner. Process
placement is separate: initially one OS process per active catalog, later
possibly several isolated catalog owners in one process. Ownership identity,
catalog lock and lifecycle always belong to the logical catalog.

```
Catalog Router
  -> Knowledge Owner        (shared knowledge catalog)
  -> Tenant Knowledge Owner (one catalog per customer)
  -> Memory Owner           (existing mem0 memory catalog)
  -> separate stores        (SWE run store, Jev cache; not knowledge Owners)
```

`tenants/<customer>/knowledge` is the isolation boundary; no extra tenant logic
is added inside the graph. A Catalog Router selects catalog + Owner before any
graph access. Direct writers are forbidden in owner mode.

## Catalog kinds

| Kind | Storage | Owner |
| --- | --- | --- |
| knowledge | `overgraph/knowledge` | Knowledge Owner |
| tenant_knowledge | `overgraph/tenants/<customer>/knowledge` | Tenant Knowledge Owner for that customer |
| memory | `overgraph/memory` | Memory Owner |
| workflow / jev cache | separate stores | not migrated to knowledge; own model if shared |

## Implementation order

1. **Legal claims/evidence** on the existing Knowledge Owner.
   - One vertical claim operation: claim node + evidence links + support edges
     in one Owner batch; reads (claim identity, evidence, support validity,
     supersession) through the Owner read protocol.
   - Preserve identities, relations, validity windows and provenance.
   - Two-client acceptance: A writes, B reads immediately; revoke/delete is
     visible without local caches.
2. **Owner routing/lifecycle generalization**: catalog registry, one logical
   owner per active catalog, per-catalog socket/lock, startup/shutdown.
3. **Document QA per tenant catalog**: move `TenantCatalogs` behind a Tenant
   Knowledge Owner; no direct knowledge writes.
4. **Memory Owner**: keep mem0 and the existing memory catalog; replace local
   catalog access with the Owner transaction/read model.
5. **SWE run store / Jev cache**: decide per store from actual sharing and
   concurrency; do not migrate merely because Overgraph is used.

## Readiness

`write_paths_ready` must become per catalog kind/function, not a global claim.
The global flag remains `false` until every relevant catalog type has its own
Owner acceptance test. Static allowlist absence is never sufficient.

## Acceptance per catalog type

- Owner + two real backend processes.
- Local knowledge/memory writes forbidden in backend processes.
- Writer A creates/updates/deletes/revokes; B observes immediately.
- Restart and stale-read paths behave explicitly.
- Only then set the relevant readiness flag.

## Current state

Legal claims/evidence production paths are migrated to the existing Knowledge
Owner (`owner_legal.py`): atomic claim+evidence+support batch, owner reads for
identity/status/evidence/answers/supersession, two owner clients verified.
Document QA still uses per-tenant catalogs; mem0 still uses the separate memory
catalog; tenant and memory Owners are the next slices. Runtime guard blocks
direct knowledge writes in owner mode. `write_paths_ready` remains false.
