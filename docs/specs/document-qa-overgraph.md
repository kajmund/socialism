# Persistent document Q&A in OverGraph

Lock and multiprocess experiment: **approved and frozen**
(`document-qa-lock-close-v1`). Do not add more lock machinery.
Document-chat persist and exact reuse are in. Document ingest
Step A writes TextUnits through `document_catalog_write`. Do not
wire semantic reuse or Tabular Review without a separate
decision. Do not import `experiments/overgraph_ingest` into
`backend/app`.

Q&A is stored when a user already has an analysis, not when a
document is ingested. A previous answer is a cache with provenance, not a verified
legal fact. Exact reuse does not raise its reliability.

## Frozen architecture

One tenant → one OverGraph file → one exclusive lifecycle lock →
one active Catalog.

The backend process owns the tenant file for long stretches.
Workers leave graph writes with that owner. They do not open the
same file. A second process may take the file only through a
deliberate close-and-handoff.

`flock` is advisory. Every future opener — document ingest, tags,
Q&A, expert tools — must go through `TenantCatalogs`. There is no
second open path.

The measured lock times are from local APFS. They are not a
claim about network filesystems.

Writeback and exact workspace reuse are in place. Inventory and
the remaining wiring:
[document-qa-graph-owner-writeback.md](document-qa-graph-owner-writeback.md).

## Inventory

| Surface | What exists today | Relation to this spec |
|---|---|---|
| `CanonicalDocument` → `DocumentVersion` → `TextUnit` | Postgres spine in `models.py` / `knowledge/units.py` | Reused. Q&A hangs on `DocumentVersion`. |
| Production OverGraph | One shared `OVERGRAPH_DIR/knowledge` (3072) + `memory` (1536) | Isolation today is `scope.*` labels before top-k, not per-tenant files. |
| `Catalog` | Process-owned wrapper, `RLock` so a read cannot overlap a write | One writer process. Same-file access is serialized. |
| Graph v2 outbox | `GraphIngestWork` after research commit | Pattern to copy: persist after the user already has the answer. Different payload. |
| `KnowledgeQuestionRow` | Research `ANSWERED_BY` DAG in Postgres | Not document-chat Q&A. Do not reuse as this store. |
| Document chat | `workspace_chat_turn` → research job → exact reuse or `compose_research_answer` | Persists `retrieved_evidence`. Exact `ANSWERED` reuse only. |
| Tabular Review | `experiments/overgraph_ingest` only | Statuses `ANSWERED` / `NOT_FOUND` / `UNCERTAIN` reused. No backend `answer_cell`. |
| Embeddings | `text-embedding-3-large` / `embedding_cache_dir` | Unchanged. Question vectors are stored on Q&A nodes only. |
| Workspace access | `resolve_readable_workspace_ids` + source membership | Still required inside the tenant file. `Viewer` is the experimental adapter. |

Tabular `answer_cell`, default hybrid retrieval, and TextUnit
embeddings are not part of this work.

## Tenant files

Each tenant gets its own OverGraph directory:

```text
{overgraph_dir}/tenants/{customer_id}/knowledge
```

`customer_id` is a verified positive integer from backend
authorization. The client cannot pass a path. Isolation is the
file, not a tenant filter on every query. Workspace and document
permissions still apply inside that file.

Production `open_runtime()` still opens the shared catalogs.
`start_graph_owner` attaches `TenantCatalogs` for tenant writes.

## Data model

```text
CanonicalDocument
  HAS_VERSION → DocumentVersion
  HAS_QUESTION → Question
DocumentVersion
  CONTAINS → TextUnit
Question
  ABOUT_VERSION → DocumentVersion
  HAS_ANSWER → Answer
Answer
  HAS_POST → AnswerPost
  HAS_REVIEW → ReviewEvent
AnswerPost
  CITES → TextUnit
```

Question identity for exact reuse:

`normalized question + document_version_id + kind + method + model
+ model_version + examined_scope + question_context`

Stored as `qa:q:{customer_id}:{sha256}`. A new document version
gets a new key. Historical Q&A stays on the old version.

`examined_scope` records what was actually analyzed.
Workspace research is `retrieved_evidence`, not
`whole_document`. `NOT_FOUND` / `UNCERTAIN` are stored but never
returned as an exact hit. A previous judgment does not become
more reliable by being reused.

Answer statuses stay `ANSWERED`, `NOT_FOUND`, `UNCERTAIN`.
`NOT_FOUND` means the examined material did not contain the
information, not that it is proven absent.

An exact quote is a source excerpt. It is not a legal holding.

## Persist and reuse

1. An existing analysis produces the answer.
2. The user is given that answer.
3. Writeback enqueues the record. Flush writes the tenant graph.
4. If writeback fails, the user still has the answer.

Exact reuse is the only cache hit. It requires the same document
version, analysis contract, examined scope, question context, and
document/version permission. Semantic neighbors are candidates.
They never set `reuse=exact`. Workspace research may reuse an
`ANSWERED` hit before it starts a new investigation.

User review: `approve` / `reject`. History is kept as
`ReviewEvent` nodes. A verified answer beats an unreviewed one.
Rejected answers are never reused as approved.

Archive sets `archived=1` and keeps Q&A. Purge deletes Q&A,
review events, citation stubs, embeddings, and pending outbox
rows so a later flush cannot recreate them.

Ingest (`ingest_document_units` / `document_catalog_write`) does
not create `Question` nodes. Searchable text is not Q&A.

## Concurrent access

OverGraph documents that opening the same directory from multiple
processes is not supported and may corrupt data. There is no
engine file lock: the second `open()` is accepted.

Socialism therefore holds an exclusive `flock` on
`tenants/{customer_id}/tenant.lock` from **before**
`OverGraph.open` until **after** `close`. A write-only lock is
not enough: a later owner `close()` still hits WAL errors if
another process opened in between.

`TenantCatalogs` is the only opener in `document_qa`. The lock
file sits next to `knowledge/`, not inside it.

Two OS processes, same tenant file
(`tests/test_document_qa_multiprocess.py`):

| Setup | Without lock | With lifecycle `flock` |
|---|---|---|
| A writes, syncs, closes. B opens and reads. | Safe | Safe |
| Two processes overlap `open()` | Lost write, WAL close errors | B waits. Both writes survive. No WAL error. |
| API holds the file. Worker writes and closes. | Owner close fails | Worker waits for the owner to close. Both keys survive. |
| Owner `sync()` then `os._exit` without `close` | — | OS releases `flock`. Next process opens and sees the write. |

Measured handoff cost (dimension 8):

| Step | Time |
|---|---:|
| `flock` when free | 0.005 ms |
| Cold `OverGraph.open` | 19 ms |
| Warm `open` | 1.2 ms |
| `close` (includes background flush) | 81–86 ms |
| Waiter `lock_wait` while owner holds ~300 ms | 421 ms |
| Exact Q&A lookup (already open) | 0.05 ms |

`close()` is the expensive step. It is much slower than a Q&A
lookup. Do not open and close the tenant file per chat question.
Keep a long-lived Catalog for retrieval. Hand the lock over only
when a worker or maintenance process must own the file.

Minimum write ownership:

1. Exactly one OS process may have a given tenant directory open.
2. That process holds `tenant.lock` for the whole Catalog
   lifecycle.
3. The next process opens only after the owner `close()` and
   lock release.
4. Chat keeps the Catalog open. Workers send work to the owner,
   or wait for a deliberate handoff.

Q&A nodes, exact reuse, and semantic candidates are unchanged.

## Measurements

Local fixture, dimension 8, one question / answer / citation.
Replace with production-dimension numbers before any
integration decision.

| Metric | Measured | Test bound | Meaning |
|---|---|---|---|
| Persist | 0.56 ms | < 2000 ms | Write question, answer, posts, cites |
| Exact reuse | 0.05 ms | < 500 ms | Key lookup + permission + preferred answer |
| Semantic candidates | 0.07 ms | < 500 ms | Dense search over `Question` only |
| Exact cache | `reuse=exact` | exact only | Same normalized question and contract |
| Semantic cache | `reuse=none` | never exact | Similar vector is not a hit |
| Tenant file after sync | 4 KB | < 5 MB | Manifest + WAL |
| Tenant file after close | 20 KB | < 5 MB | Same fixture, flushed |
| Warm `open` | 1.2 ms | < 2000 ms | Lifecycle lock already held or just acquired |
| `close` | 81–86 ms | < 2000 ms | Flush/WAL finish before lock release |

Storage cost in production is one Question vector at the
configured embedding dimension, plus answer/post/review nodes
and citation excerpts. No extra Jev call is required to save.

## Reuse risks

- Semantic similarity is not identity. Auto-approving it would
  treat a different legal question as answered.
- A quote can be exact and the interpretation still wrong.
- `NOT_FOUND` is not absence from the document.
- A new `DocumentVersion` must not inherit old answers as
  current. Old questions may be candidates only.
- A rejected answer must not come back as approved.
- Tenant isolation depends on opening the right file from
  verified `customer_id`. A client-supplied path would break it.

## Production integration

The lock experiment is closed. Do not reopen it. Tenant Q&A
writeback uses the existing `graph_ingest_work` outbox. The
producer never opens OverGraph. Legal jobs without a kind still
write the shared catalog.

Not in this delivery:

- Replace the shared knowledge catalog with tenant files
- Semantic reuse of a previous answer
- Write Q&A from Tabular Review
- Call the existing embedding provider for question vectors
- Open a tenant file from a second backend or worker process

Code lives in `backend/app/services/document_qa/`.
`workspace_chat_turn` must not import it. Document ingest may
enqueue `document_catalog_write` only. The research composer
may enqueue a finished one-document answer.
