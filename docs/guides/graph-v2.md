# Graph v2

Graph v2 stores domain-neutral nodes, fact edges, identifiers, provenance and
fact-to-fact relations. IDs are stable SHA-256 keys independent of database
sequences and supporting documents. OverGraph is the target engine for that
model; see [overgraph-knowledge-engine.md](../specs/overgraph-knowledge-engine.md).
Research reads facts and TextUnits from OverGraph. Postgres Graph v2 tables
remain for grafens egna tester, svarsavsnitt kopplade till EvidenceSet och
legal write-back tills de vägarna är helt flyttade. De är inte en andra
auktoritativ kopia av TextUnits.

## Identity and resolution

Strong identifiers are scoped aliases (`graph_identifiers`). Weak names are
scoped by node type and context before a semantic node judge may merge them.
Facts are scoped by source, target, namespaced predicate, context and temporal
occurrence. Exact normalized text reuses the edge. A different wording must
be judged SAME, DISTINCT or CONTRADICTS. A SAME decision adds provenance to
the old fact. CONTRADICTS stores another fact and a `core.contradicts` link;
only an explicit, structurally guarded operation can invalidate a prior fact.

`graph_fact_sources` references episodes or TextUnits. Provenance is never
included in fact identity. TextUnit references are checked against the tenant
boundary before write. Customer facts may reference shared nodes, but may not
reference another customer's nodes. Public tables have RLS enabled without
Data API policies; backend owner connections manage writes.

`core.question` nodes project canonical KnowledgeQuestions. Research lineage
projects as `research.decomposed_to` fact edges. The existing research tables
remain the orchestration record while the graph representation converges.
Research commits its evidence and GraphIngestWork outbox row together. Embedding
and semantic resolution happen in the background worker, so graph writeback
does not hold research completion open. Exact edge identity is checked before
embedding; unresolved fact texts are embedded as one batch and only locally
shortlisted ambiguous nodes/facts reach the semantic judge.

`graph_embedding_cache` is shared across tenants and content-addressed by model,
the configured `EMBEDDING_MODEL_REVISION`, dimension, purpose and SHA-256 of the
exact UTF-8 input. The embedding service receives that same unmodified input:
case, whitespace, punctuation and Unicode representation are not normalized.
This applies to source chunks, queries and fact texts using this shared adapter;
normalized graph edge identity remains a separate concern. It stores no tenant,
source, run, provenance or raw text. Database leases coordinate simultaneous
cache misses across workers; changing the model revision produces a new cache
entry without rewriting graph facts.

The default purpose is `text.exact.v2`, which does not read the old normalized
`text.v1` namespace. Old cache rows remain available for inspection; no legacy
lookup is attempted. The existing SQL column `normalized_text_hash` holds the
exact input hash for this new purpose. Already materialized TextUnit/index
vectors and graph-fact vectors are not migrated or recomputed by this change.
Different documents retain their own TextUnits and vector projections even
when an embedding is reused.

## Shared chunk text and temporal occurrences

`shared_text_chunks` stores exact text once, keyed by SHA-256 of its UTF-8 bytes.
Each `text_units` row references that content and retains its own document,
version, scope, locator, ordinal and temporal metadata. Shared content has no
tenant or provenance fields and is not a retrieval or authorization boundary;
reads still select scoped TextUnits. PostgreSQL RLS and revoked client-role
grants keep the content table backend-only.

Ingestion validates the incoming SHA before writing, resolves overlapping
batches in sorted hash order, and rejects an existing hash with different text.
Database triggers reject changes to stored content and retargeting an existing
TextUnit to different content. A source changing A → B → A creates a third
version occurrence referencing the original A chunk, preserving the earlier
version history. Removing one occurrence does not delete shared text or other
documents' references; no customer-material deletion API is introduced here.

Text is eagerly joined when TextUnits are loaded, so it is materialized before
the database connection is released for embedding or vector-store work. The
embedding cache remains independently keyed by model, revision, dimension,
purpose and exact-text SHA. Vector projections still carry document-specific
text and provenance. Canonical source ingestion writes the new occurrence's
known keys directly with `upsert_chunks`, retaining earlier versions' vectors.
It does not list the index or delete previous projections. Current source
selection comes from SQL's current version; frozen historical source references
can retrieve their own TextUnit vectors by exact document and chunk keys.
The Jev/TTL answer-review pipeline is unchanged.

Index repair materializes current document/TextUnit inputs, ends its read
transaction and then checks or writes known keys. A supplied active transaction
is rejected before any external call, preserving the caller's pending work.
An interrupted index write propagates the error; replaying the persisted
version checks the same keys and uses the embedding cache to complete it.
Already-deleted historical vectors are not reconstructed by this change.
Uploaded customer files and editable document-item indexes retain their
existing replacement/deletion behavior; this change covers canonical sources.

Migration `e8c2f4a1b6d0` validates all existing TextUnit hashes, copies unique
text into the shared table and replaces the old text column with a foreign key.
It preserves TextUnit IDs, supporting references and version metadata without
embedding calls or vector reindexing. A mismatched hash aborts rather than
rehashing historical identities. PostgreSQL locks the affected table during
the migration; SQLite requires foreign keys disabled on the migration
connection before its batch-table rewrite, to preserve incoming references.
Downgrade reconstructs each occurrence's text from the shared table.

## Retrieval and portability

Retrieval fuses full-text matches and embedding similarity with reciprocal
rank fusion, then expands bounded graph neighbourhoods by node ID. PostgreSQL
adds a GIN full-text index. The OverGraph engine replaces that Python fusion
with native dense, sparse and hybrid search plus graph-scoped ranking. Community
summaries should be recomputed from fact edges and provenance, never used as an
authoritative fact store.

The legal research adapter projects meaningful subject and concept/value nodes;
the full assertion is held by its fact edge and only its supporting TextUnits
are attached as provenance. The legacy claims remain an extraction/orchestration
boundary during cutover, rather than the Graph v2 identity model.
