# TextUnit knowledge architecture

All citable sources share one ingest pipeline. The system reasons from `TextUnit`, not from documents, excerpts, or domain-specific raw results.

```text
Source
  → Canonical Document
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
Document → Section → TextUnit
TextUnit → Claim / Entity / Relationship / Q&A / Research evidence
```

Microsoft GraphRAG inspired the primitives (`Document`, `TextUnit`, later `Entity` / `Relationship` / `Claim`). Socialism owns the implementation. GraphRAG is not a runtime dependency, and community detection / Global Search are out of scope until a later phase.

## Phase 1 — landed

Uploaded documents now ingest as `CanonicalDocument` → `DocumentSection` → `TextUnit`.

- Structure-aware segmentation prefers markup headings, numbered titles, and short all-caps display lines.
- If no structure is found: extracted block boundaries, then paragraphs, then sentence-safe size splits.
- Size-based splitting happens only inside a section.
- TextUnit IDs are stable for an unchanged passage (`document_id`, `version`, `locator`, `content_hash`).
- Embeddings are generated from TextUnit text. `KnowledgeChunk` is the vector-store projection of a TextUnit (`chunk_id == text_unit_id`).
- Q&A generation reads neighbouring TextUnits, not a separate 16k-char block batch.
- `DocumentKnowledgeItem` keeps exact quotes and PDF anchors, and adds `supporting_text_unit_ids`.
- Core knowledge modules stay domain-neutral. Swedish law, medicine, and economics belong in adapters.

Tables: `canonical_documents`, `document_sections`, `text_units`, `document_knowledge_item_text_units`.

Temporal fields present from the start: `valid_from` / `valid_to` (valid time) and `ingested_at` / `superseded_at` (system time). Re-ingest supersedes removed units instead of deleting them.

## Next phases

### Phase 2 — Q&A routing

Use Jev as a cheap passage gate: which TextUnits are likely to contain revisitable facts? Group only those neighbours before LLM Q&A. Keep exact-quote grounding.

### Phase 3 — lagen.nu as a document provider

Resolve a stable source identity (for example NJA 2005 s. 142). Reuse the existing canonical document when the version matches; otherwise fetch → ingest → segment → embed. Legal extraction produces claims that point at TextUnits. Do not keep a parallel `LegalResearchResult.raw_text` as the long-term source representation.

### Phase 4 — research against ingested knowledge

`ResearchNeed` → existing questions / claims / TextUnits → embedding candidates → Jev relevance → fetch new documents only when needed → freeze `EvidenceSet` from grounded TextUnits and claims.

### Phase 5 — temporal graph

Claims and relationships carry valid time and system time. Graph mutations emit events (`DOCUMENT_ADDED`, `TEXT_UNIT_SUPERSEDED`, `CLAIM_ADDED`, `EDGE_ADDED`, …). Frozen EvidenceSets record `graph_revision_at_freeze`.

### Phase 6 — revalidation

Impact lookup over the graph neighbourhood, then Jev as an impact gate. Frozen EvidenceSets get a separate `RevalidationState`. Do not mutate frozen snapshots.

## Design constraints

- Domain-neutral core. No Swedish-law, medical, or economic vocabulary in `app/services/knowledge/`.
- Provenance first. Derived objects point at TextUnit IDs.
- No silent truth mutation. Supersede; do not overwrite history.
- Deterministic work (IDs, hashes, adjacency, embeddings, source identity) before LLM/Jev.
- Jev routes and classifies. The LLM extracts and formulates. Neither replaces source provenance.
