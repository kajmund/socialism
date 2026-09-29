# Graph v2

Graph v2 stores domain-neutral nodes, fact edges, identifiers, provenance and
fact-to-fact relations. The SQL tables map directly to Neo4j labels,
relationships and properties; IDs are stable SHA-256 keys independent of
database sequences and supporting documents.

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
the configured `EMBEDDING_MODEL_REVISION`, dimension, purpose and normalized-text hash. It stores no tenant,
source, run, provenance or raw text. Database leases coordinate simultaneous
cache misses across workers; changing the model revision produces a new cache
entry without rewriting graph facts.

## Retrieval and portability

Retrieval fuses full-text matches and embedding similarity with reciprocal
rank fusion, then expands bounded graph neighbourhoods by node ID. PostgreSQL
adds a GIN full-text index. Embeddings currently use portable JSON storage
and a bounded semantic scan; a vector index and asynchronous ingestion are
required for large corpora. Community summaries should be recomputed from
fact edges and provenance, never used as an authoritative fact store.

The legal research adapter projects meaningful subject and concept/value nodes;
the full assertion is held by its fact edge and only its supporting TextUnits
are attached as provenance. The legacy claims remain an extraction/orchestration
boundary during cutover, rather than the Graph v2 identity model.
