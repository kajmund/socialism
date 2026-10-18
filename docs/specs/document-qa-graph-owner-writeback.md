# Graph owner writeback

Inventory and the first tenant-Q&A writeback. No new queue, no
new graph service, no more lock code. Legal write-back stays on
the shared catalog. Chat, Tabular Review, and ingest are not
wired.

The lock experiment is closed (`document-qa-lock-close-v1`).
This note only answers: where graph jobs are born, who runs
them, and how tenant Q&A can reach the process that already
owns `TenantCatalogs`.

## Inventory

Socialism already has several “queues”. Only one is the durable
graph outbox.

| Mechanism | Durable? | Who enqueues | Who runs it | Opens OverGraph? |
|---|---|---|---|---|
| `graph_ingest_work` / `enqueue_legal_graph` | Yes, Postgres | Legal research write-back after claims are accepted | `start_graph_ingest_loop` in the **backend process** | Yes, shared `require_knowledge()` |
| In-memory `GraphWritebackQueue` | No | lagen.nu research, before commit | Same request, then `enqueue_legal_graph` | No |
| Experimental `QaOutbox` | No | Tests only | Test `flush()` | Yes, `TenantCatalogs` |
| `jobs.enqueue_job` | Job row | API / tools | Backend job worker | Document ingest persists Postgres, then enqueues `document_catalog_write` |
| Research reclaim loop | Lease rows | Research start | Same backend process | Reads OverGraph; does not consume `GraphIngestWork` |

The durable graph path is already the model we want:

```text
Research commit
    → enqueue_legal_graph (same Postgres transaction as evidence)
    → graph_ingest_work pending
    → backend asyncio loop (every 5s, batch 10)
    → claim_graph_work (skip_locked, 5 min lease, retry_at)
    → write_legal_facts
    → require_knowledge()  (shared catalog today)
```

It is **not** consumed by a separate worker process. The loop
starts in `app/main.py` next to `open_runtime()`, when
`graph_ingest_loop_enabled` is true (default on, off in tests).
That flag is independent of `research_worker_loop_enabled`.
Do not treat the split as a full worker-startup refactor.
Do not move this loop into research workers.

Producer today: `lagen_nu.graph_writeback.persist_pending_graph_writes`
after accepted claims. Payload is legal claims and entities.
Work id is `stable_id(scope, research_need_id, payload)`.
Duplicate enqueue is a no-op (`IntegrityError`).

Consumer retry: transient errors go back to `pending` with
backoff. Permanent errors (`PermanentGraphError`, bad payload)
mark `failed`. Completion is a compare-and-set on
`status=processing` and `attempts`.

Idempotency today: enqueue key is stable; fact and node writes
reuse Graph v2 / OverGraph identity keys. A crash after
OverGraph upsert and before `completed` retries the same keys.

## Gaps for tenant Q&A

1. The loop writes the **shared** knowledge catalog, not
   `TenantCatalogs`.
2. The payload has no Q&A, tag, or document-ingest kind.
3. `QaOutbox` must not become a second production queue.
4. Two backend replicas would both start the loop
   (`skip_locked`). That is fine for a Postgres row. It is not
   fine if both open the same tenant file. One backend owns all
   tenant files until we have customers that need otherwise.

## Integration

Keep `graph_ingest_work` as the durable queue. Keep the backend
loop as the only consumer. Add a job kind the same loop can
dispatch.

```text
Q&A / tags / ingest / experts
        → enqueue on graph_ingest_work (new kind, stable id)
        → existing claim / retry / complete
        → backend graph owner
        → TenantCatalogs.open_for(customer_id)
        → tenant OverGraph upsert by identity key
```

Rules:

- Producers never call `OverGraph.open` or `open_catalog` on a
  tenant path.
- The consumer already has the Catalog open. No `open`/`close`
  per job.
- Identity keys make a replay a no-op, not a duplicate node.
- Failed Q&A writeback must not take the user answer with it.
- Do not invent a new table, broker, or graph service.
- Do not run `process_graph_work` from a process that does not
  own `TenantCatalogs`.

Legal write-back can stay on `require_knowledge()` until the
shared catalog is retired. Tenant kinds go through
`TenantCatalogs` only.

## Implemented vertical chain

`enqueue_document_qa` writes `kind=document_qa_write` on
`graph_ingest_work`. The producer never opens OverGraph. Tenant
and document version are checked against
`CanonicalDocument` / `DocumentVersion` and `row.customer_id`.

The backend loop peeks `kind`. Legal payloads without a kind
still call `write_legal_facts` → `require_knowledge()`. Q&A jobs
close the Postgres session, then `TenantCatalogs.open_for` from
the row's `customer_id`. Replay upserts the same identity keys.

`graph_ingest_loop_enabled` starts the graph loop without
research reclaim. Tests turn both flags off. Do not treat that
as a full worker-startup refactor.

Document chat persist: `compose_research_answer` enqueues a
one-document `retrieved_evidence` answer after the user already
has it. Exact reuse may return that `ANSWERED` hit before a new
investigation. `NOT_FOUND` / `UNCERTAIN` are not hits. No
semantic cache. Tabular Review is not wired. Document ingest
Step A enqueues `document_catalog_write` for TextUnits.
