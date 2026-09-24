# TextUnit knowledge architecture

All citable sources share one ingest pipeline. The system reasons from `TextUnit`, not from documents, excerpts, or domain-specific raw results.

```text
Source
  → Canonical Document
  → Document Version
  → Extraction
  → Structural segmentation
  → Sections
  → TextUnits
  → Embeddings
  → (later) Entity / Claim / Relationship
  → Temporal Knowledge Graph
```

Everything the system can cite is a `Document`. Everything it reasons from must ground in one or more `TextUnits`:

```text
CanonicalDocument → DocumentVersion → Section → TextUnit
TextUnit → Claim / Entity / Relationship / Q&A / Research evidence
```

Microsoft GraphRAG inspired the primitives (`Document`, `TextUnit`, later `Entity` / `Relationship` / `Claim`). Socialism owns the implementation. GraphRAG is not a runtime dependency, and community detection / Global Search are out of scope until a later phase.

## Phase 1 — landed

Uploaded documents now ingest as `CanonicalDocument` → `DocumentVersion` → `DocumentSection` → `TextUnit`.

- `CanonicalDocument` is stable source identity: `(customer_id, source_type, canonical_uri)`.
- `DocumentVersion` is an immutable temporal occurrence. Reuse only when the incoming `content_hash` already matches the current version. A historical hash that returns creates a new version row. Provider `version` is metadata only.
- Structure-aware segmentation prefers markup headings, numbered titles, and short all-caps display lines.
- If no structure is found: extracted block boundaries, then paragraphs, then sentence-safe size splits.
- Size-based splitting happens only inside a section.
- Section and TextUnit IDs are scoped to `document_version_id`. Same passage in the same version keeps the same ID.
- Embeddings are generated from TextUnit text. `KnowledgeChunk` is the vector-store projection of a TextUnit (`chunk_id == text_unit_id`).
- Q&A generation reads neighbouring TextUnits in the same section. Size packing stays inside a section and no longer spans the whole document.
- `DocumentKnowledgeItem` keeps exact quotes and PDF anchors, and adds `supporting_text_unit_ids`.
- Core knowledge modules stay domain-neutral. Swedish law, medicine, and economics belong in adapters.

Tables: `canonical_documents`, `document_versions`, `document_sections`, `text_units`, `document_knowledge_item_text_units`.

A version is immutable after persist, including its system-time interval. Same source + same `content_hash` reuses the current `DocumentVersion` only when that version is still current, and then skips new TextUnits and embeddings. Any other ingest — new hash or a historical hash that returns — supersedes the current version and inserts a new snapshot. The same content may recur; the same temporal version may not. Historical versions and their TextUnits stay queryable. `get_current_document_version(document_id)` is `superseded_at IS NULL`; at most one current version exists per document.

Valid time (`valid_from` / `valid_to`) and system time (`ingested_at` / `superseded_at`) live on `DocumentVersion`. TextUnits keep valid-time fields for later claim-level temporality. A future frozen EvidenceSet can store `document_version_ids` + `text_unit_ids` and reproduce the exact snapshot.

Hard delete is reserved for explicit tenant/source deletion. Re-ingest supersedes; it does not delete historical versions or TextUnits.

External providers do not go through `StoredObject`. After they have bytes and a stable source identity they call `ingest_extracted_source`:

```text
resolve (source_type, canonical_uri)
  → ingest_extracted_source(extracted, source_type, canonical_uri)
      → resolve CanonicalDocument
      → reuse or create DocumentVersion
      → same Section / TextUnit persist + embeddings
```

Same content hash reuses the existing document id and current version when that version is still current. A new hash, or a historical hash that returns, keeps the same canonical document and adds a new occurrence.

## Next phases

### Phase 2 — Q&A routing

Section-neighbour grouping is in place. Next: use Jev as a cheap passage gate so only TextUnits likely to contain revisitable facts are sent to LLM Q&A. Keep exact-quote grounding.

### Phase 3 — lagen.nu as a document provider

`ingest_lagen_nu_document` maps a fetched `LagenNuDocument` onto `ingest_extracted_source`. The adapter lives in `app/services/lagen_nu/`; the knowledge core stays domain-neutral.

- `source_type` is `lagen_nu`.
- Canonical identity is the fragment-free `https://lagen.nu/…` URI. Pinpoint fragments stay on evidence locators, not on `CanonicalDocument`.
- `content_hash` is SHA-256 of the document plaintext.
- Same current hash reuses the current `DocumentVersion` and skips embeddings.
- A new hash, or a historical hash that returns, supersedes and inserts a new occurrence.
- Research reads those TextUnits. MCP `get_document` runs only when the customer has no current version. Pinpoint stays on evidence locators.
- `LegalResearchResult.raw_text` is the retrieved TextUnit corpus, not a parallel RawSource cache of MCP text.
- Legal claim extraction is still later.

### Phase 4 — passage routing in front of LegalInterpreter

lagen.nu research ranks current TextUnits in-process (question embed + ingest vectors, cosine), Jev `relevant_to_question` keep/drops the top-K seeds, then expands same-section neighbours (`+/-1`). Neighbours are added after Jev so low-score context is not dropped. `LegalInterpreter` sees the expanded set, clipped to a deterministic char budget. Empty keep is `not_found` / `irrelevant_relation`. Jev or embedding failure is `selection_failed`. Production does not send the whole judgment. Next: freeze `EvidenceSet` from grounded TextUnits and claims.

### Phase 4b — claims on TextUnits

A `KnowledgeClaim` is an assertion. Support is `SUPPORTED_BY` one or more TextUnits (`knowledge_claims` + `knowledge_claim_text_units`). The knowledge core does not interpret predicate strings. The lagen.nu adapter projects `legal_claims` after interpret and grounds each citation quote to the interpreted units. A quote that is not in those units is `citation_grounding_failed`.

`ResearchNeed` → `ANSWERED_BY` → Claim (`knowledge_claim_answers`, keyed by `question_key` + `source_type`) so reuse can find grounded answers instead of only evidence excerpts.

Runtime needs canonicalize to `KnowledgeQuestion` before live retrieval (identity_key = normalized `question_key`). Fresh grounded claims close their source type. Excerpt-only graph hits stay candidates and do not skip providers. Remaining source types are gaps and are the only natures retrieved. Stale claims are gaps.

### Phase 4c — entities and relationships

The knowledge core stores named `Entity` nodes and typed `Relationship` edges. Core relations are closed: `ABOUT`, `SUPPORTED_BY`, `CONTRADICTS`, `PART_OF`, `SAME_AS`. Adapters add namespaced relations (`legal.cites`, `legal.applies`, `legal.decided_by`). Node kinds are `entity`, `claim`, `text_unit`, and `document`. Predicate and entity_type strings stay opaque in the core.

The lagen.nu adapter projects explicit interpretation fields onto that graph after claims are grounded: source / court / issue / provision entities, `ABOUT` from claims, `SUPPORTED_BY` onto TextUnits, `SAME_AS` for an identifier alias, and the legal edges above. No prose inference.

### Phase 5 — temporal graph

Claims and relationships carry valid time and system time. Graph mutations emit events (`DOCUMENT_ADDED`, `DOCUMENT_VERSION_ADDED`, `TEXT_UNIT_ADDED`, `CLAIM_ADDED`, `EDGE_ADDED`, …). Frozen EvidenceSets record `document_version_ids`, `text_unit_ids`, and `graph_revision_at_freeze`.

### Phase 6 — revalidation

Impact lookup over the graph neighbourhood, then Jev as an impact gate. Frozen EvidenceSets get a separate `RevalidationState`. Do not mutate frozen snapshots.

## Design constraints

- Domain-neutral core. No Swedish-law, medical, or economic vocabulary in `app/services/knowledge/`.
- Provenance first. Derived objects point at TextUnit IDs, which resolve to a DocumentVersion.
- No silent truth mutation. Supersede; do not overwrite history.
- Deterministic work (IDs, hashes, adjacency, embeddings, source identity) before LLM/Jev.
- Jev routes and classifies. The LLM extracts and formulates. Neither replaces source provenance.
