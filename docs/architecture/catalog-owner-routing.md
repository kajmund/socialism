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

## Routing foundation

`app/services/overgraph/owner_registry.py` provides the catalog router: routes
are keyed by `(catalog kind, customer_id)` and each route must have a healthy
Owner endpoint. The registry does not start processes; deployment owns one
Owner process per active catalog. Tests verify knowledge/tenant/memory routing
and that identical keys in two tenant catalogs stay isolated.

Tenant routes are configured with `OVERGRAPH_TENANT_OWNER_SOCKETS` as
`customer_id=socket` entries (comma separated, for example
`1=/run/tenant-1.sock,2=/run/tenant-2.sock`). The backend connects and
health-checks every configured route at startup; malformed or unreachable
routes fail startup. An unconfigured tenant has no route, so tenant access
fails explicitly instead of opening a local catalog. Tenant owner health is
reported by `GET /health/overgraph-owner`.

## Current state

Legal claims/evidence production paths are migrated to the existing Knowledge
Owner (`owner_legal.py`): atomic claim+evidence+support batch, owner reads for
identity/status/evidence/answers/supersession, two owner clients verified.
Document QA has an Owner-backed Q&A repository (`document_qa/owner_qa.py`,
`owner_qa_lifecycle.py`, `owner_qa_retrieve.py`): atomic owner batch for
document/version/question/answer/posts/citations, owner reads for reuse,
review, archive and purge. Document ingest and the type index also have
Owner-native writes: `owner_ingest.py` publishes document/version/TextUnits,
embeddings and edges in one batch, and `owner_document_index.py` writes
effective type/category membership and reads a type index with paginated Owner
queries. Seven owner tests cover two clients, duplicate publish, invalid
citation rejection, reuse, review, archive/purge, tenant isolation, atomic
ingest and index reclassification. Production Document QA callers still use per-tenant catalogs until
tenant Knowledge Owner lifecycle is wired; the backend can now configure and
health-check tenant Owner routes, but the owner repository is not yet on the
request path. mem0 still uses the separate memory catalog; tenant and
memory Owners are the next slices. Runtime guard blocks direct knowledge writes
in owner mode. `write_paths_ready` remains false.
