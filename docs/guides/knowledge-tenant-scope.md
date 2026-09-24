# Knowledge tenant scope

Hard architectural invariant for the knowledge pipeline: customer/private knowledge may consume shared/global knowledge, but must never leak upward into shared/global knowledge.

```text
shared/global knowledge
        ↓ readable by customer-scoped research/graph
customer/private knowledge
        ✗ must never publish/reuse into shared/global
```

## Scope model

One persist/reuse type, `KnowledgeTenantScope` in `app/database/knowledge_scope.py` (Alembic-safe; services re-export it):

| `scope_type` | `customer_id` | `scope_key` |
|---|---|---|
| `shared` | `null` | `shared` |
| `customer` | required kund id | `customer:{id}` |

`customer_id` is null only when `scope_type=shared`. Missing or ambiguous persist/reuse scope fails closed. The code never infers shared from a missing kund.

Retrieval is always as a customer (`KnowledgeScope.customer_id` required). A customer reader sees:

- their own customer-scoped objects
- every shared object
- never another customer's private objects

## Tables

These tables carry `scope_type`, `scope_key`, and nullable `customer_id`, with a CHECK that the triple is consistent:

- `canonical_documents`
- `document_versions`
- `document_sections`
- `text_units`
- `knowledge_claims`
- `knowledge_claim_answers`
- `knowledge_entities`
- `knowledge_relationships`
- `knowledge_graph_events`
- `knowledge_questions` (aligned with existing `visibility` / `namespace`)

Identity uniques are scoped:

- documents: `(scope_key, source_type, canonical_uri)`
- entities: `(scope_key, entity_type, entity_key)`
- relationships: `(scope_key, relation, from/to)`

EvidenceSets stay owned by `execution_runs.customer_id`. Revalidation of a customer graph event only considers that customer's frozen sets.

Embeddings store `scope_type` + `customer_id` in chunk metadata. Search post-filters with the same visibility rule.

## How scope propagates

1. Persist entrypoints resolve `require_persist_scope(scope=..., customer_id=...)`.
2. Child rows (version, section, TextUnit, ANSWERED_BY, graph event) copy the parent object's scope. They do not infer it later.
3. ORM `before_insert` / `before_update` complete a customer scope from an explicit `customer_id`, and refuse to invent shared.
4. Query helpers use `visible_to_customer_clause` so joins cannot drop the tenant filter.

Derived objects inherit source scope. A customer document cannot grow shared claims, TextUnits, or embeddings.

## Shared → customer reuse

Allowed, and required for mixed research:

```text
customer contract + shared HD judgment → same research loop
```

Examples that stay legal:

- Customer A retrieval returns shared TextUnits plus A's private TextUnits
- A private claim may `ABOUT` a shared public entity (`Volvo AB`)
- Shared claims may `ANSWERED_BY` both A and B questions
- Canonical question lookup is tenant namespace, then public. Never another tenant.

The private claim, edge, and attributes remain `scope_type=customer`.

## Customer → shared leakage is prevented

These paths refuse to cross the tenant boundary:

- canonical document dedupe (exact `scope_key` identity)
- canonical question reuse (namespace + `scope_key` check)
- claim reuse / ANSWERED_BY lookup
- entity identity (hash includes customer vs `shared`)
- `SAME_AS` (identical scopes only)
- relationship persist (no two-customer edges; no customer endpoint on a shared edge)
- graph neighborhood (`relationships_touching` visibility clause)
- revalidation (`ExecutionRun.customer_id` of the event)
- embedding retrieval (`chunk_in_scope` / `record_in_scope`)
- semantic question match (single namespace; mixed namespaces fail)

Promoting a customer object to shared, or merging two tenants because names match, raises `KnowledgeScopeError` / `KnowledgeRelationshipError`.

## Tests

Negative isolation coverage lives in `backend/tests/test_knowledge_tenant_boundary.py`.
