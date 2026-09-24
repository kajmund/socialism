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
- Q&A generation reads neighbouring TextUnits, not a separate 16k-char block batch.
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

Use Jev as a cheap passage gate: which TextUnits are likely to contain revisitable facts? Group only those neighbours before LLM Q&A. Keep exact-quote grounding.

### Phase 3 — lagen.nu as a document provider

Resolve a stable source identity (for example NJA 2005 s. 142). Reuse the existing canonical document and current version when that version's content hash matches; otherwise fetch → ingest → new `DocumentVersion` occurrence → segment → embed. Legal extraction produces claims that point at TextUnits. Do not keep a parallel `LegalResearchResult.raw_text` as the long-term source representation.

### Phase 4 — research against ingested knowledge

`ResearchNeed` → existing questions / claims / TextUnits → embedding candidates → Jev relevance → fetch new documents only when needed → freeze `EvidenceSet` from grounded TextUnits and claims.

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
