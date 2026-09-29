# Research reuse through Graph v2

Reusable persistent knowledge for research. This is a seam on the existing engine, not a second research loop.

## Runtime vs persistent

| Layer | What it is | Where it lives |
| --- | --- | --- |
| `ResearchNeed` / `ResearchRuntimeNeed` | One Attempt/wave question plus execution/status/lineage | `research_runtime_needs`, plan snapshots |
| `ResearchNeedExecution` | Running / completed / failed for that need | `research_need_executions` |
| `KnowledgeQuestion` | Canonical persistent question identity | `knowledge_questions` + graph node |
| `GraphFact` / `GraphFactSource` | Reusable fact with canonical source grounding | `graph_facts`, `graph_fact_sources`, `text_units`, `document_versions`, `canonical_documents` |
| `EvidenceSource` / `EvidencePassage` | Canonical document and immutable unique passage | `evidence_sources`, `evidence_passages` |
| `ANSWERED_BY` / `BESVARAS_AV` | Question → passage relation | `knowledge_question_evidence_links` |
| `ResearchEvidence` / `EvidenceSet` | Frozen membership plus need lineage | `evidence_set_items`, `evidence_set_item_needs` |

A runtime need may resolve to a `KnowledgeQuestion`. Execution state never moves into the graph. A provider document is stored once as `EvidenceSource`; each distinct locator/content combination is stored once as an immutable `EvidencePassage`. EvidenceSets and KnowledgeQuestions only link to those passages. Multiple ResearchNeeds can link the same EvidenceSet item without copying source text.

Identity starts with the existing deterministic `research_question_key` (normalized casefold + whitespace) plus an explicit namespace. On an exact miss, production uses `SemanticQuestionIdentityMatcher` against the same Supabase Vector Bucket as document knowledge. Question vectors use a dedicated vector customer partition plus `knowledge_kind=knowledge_question` and namespace metadata, so ordinary document retrieval cannot return them. The canonical SQL row remains authoritative; the vector index only proposes one of the SQL candidates. Model, embedding version, and dimension are persisted together on `knowledge_questions`.

The similarity threshold and candidate bound are configured with
`RESEARCH_QUESTION_SEMANTIC_MATCH_THRESHOLD` and
`RESEARCH_QUESTION_SEMANTIC_MATCH_LIMIT`. Public and tenant questions use
different namespaces, and tenant questions cannot match another customer's
vectors.

## Target flow

```text
ResearchNeed
  → resolve/create canonical KnowledgeQuestion
  → retrieve candidates from Graph v2 facts and source TextUnits
  → retrieve external sources for unassessed needs
  → persist Claims + ANSWERED_BY
  → assess / completeness
  → follow-up KnowledgeQuestion + idempotent parent/child lineage
  → freeze EvidenceSet.grounded_refs
```

`KnowledgeQuestion` is the reusable identity. `ResearchNeed` is the execution unit for remaining gaps. Follow-ups reuse `identity_key`; they do not create a new node per wave. `knowledge_question_lineage` stores `generated_from` plus optional claim/event triggers. `QuestionRelationResolver` is reserved for later same_as/broader/narrower matching.

Executing research first calls `graph_reuse.lookup_graph_evidence`. It retrieves bounded canonical-question dependencies, hybrid lexical/semantic fact hits, and one-hop neighbours. Graph facts are hydrated only through `GraphFactSource` → `TextUnitRecord` → `DocumentVersionRecord` → `CanonicalDocumentRecord`. Runtime research never reads legacy claims or legacy Question→Evidence links as a retrieval path.

Graph hits are evidence candidates, not proof that the question is answered. A matching source type or question dependency cannot skip external sources. The existing assessment/completeness loop evaluates the combined frozen basis. This deliberately removes the former claim/source-type shortcut; it does not yet introduce an early sufficiency gate to save provider calls.

Follow-up preparation binds canonical question identities and lineage without reading legacy claims or closing needs by source type. Each accepted follow-up uses the same Graph v2 retrieval path when it executes. Freeze snapshots include `graph_fact_ids` alongside source version and TextUnit IDs.

Expert chat uses the same graph retrieval function. It includes only fresh graph evidence previously recorded in a frozen EvidenceSet from a ready/completed attempt owned by the customer. No Run, Attempt, question, or external research request is created by this read.

Legacy claim creation and Question→Evidence write-back still serve existing ingest/history consumers. They are not runtime read alternatives. Graph projection must complete before newly ingested facts become reusable.

## Scope

Namespaces are designed now so later customers do not need an unsafe compatibility fallback.

| Namespace | Key | Who can read |
| --- | --- | --- |
| `public` | `visibility=public`, `customer_id` null | Every kund, and only edges whose provenance is public |
| `tenant:{id}` | `visibility=tenant`, required `customer_id` | That kund only |

Graph retrieval reads only `shared` and `customer:{id}` scopes. Shared facts may reference only shared passages; customer facts may reference shared or same-customer passages. Inconsistent or missing grounding raises `GraphResearchError`. Source type alone never grants visibility. The namespace table above describes canonical question identity, not the retrieval engine.

Reuse also has to match the current need:

- `source_type` must be in the current `ResearchNeed.source_types`. A cached `web` hit cannot satisfy a later `swedish_law` need.
- `case_knowledge` edges store `knowledge_case_id` and are only visible to that case.
- Tenant edges store `knowledge_module` and stay inside that module.
- Reused `persistent_knowledge` items are not written back. A cache hit must not refresh `observed_at` or keep an edge `fresh` forever.

## Validity, freshness and failures

Only active facts within their validity interval are returned. Documents, versions and TextUnits must agree on scope and document identity. Superseded or out-of-interval source versions are excluded. Declared case/module scope must match the current research context; case knowledge without a declared case is excluded.

Candidate freshness is based on the source version's `ingested_at`, not a new retrieval timestamp. An optional `RESEARCH_KNOWLEDGE_FRESHNESS_MAX_AGE_SECONDS` ages out old candidates; an unset max-age adds no age limit. Validity and supersession checks always apply. Fresh candidates still cannot bypass assessment.

There is one read path. Graph, SQL, canonicalization, embedding and write-back errors propagate; they are never converted into an empty successful lookup. External provider retrieval is normal research after a successful graph read, not an error fallback. Canonical SQL and in-memory/Graphiti question adapters remain identity/write test seams; they do not provide alternate evidence reads.

Bounds use `RESEARCH_KNOWLEDGE_LOOKUP_LIMIT`. An actually empty grounded graph requires no embedding request. With graph data present, query embedding failure aborts instead of switching to lexical-only search. `research.graph_v2.retrieval.completed` reports candidate/evidence counts and `research.graph_v2.external_search` records why provider retrieval is needed.

## Lineage

`evidence_set_items.provenance.reuse`:

```json
{
  "origin": "persistent_knowledge" | "fresh_retrieval",
  "knowledge_question_id": "...",
  "relation": "ANSWERED_BY",
  "relation_sv": "BESVARAS_AV",
  "freshness": "fresh" | "stale" | "unknown",
  "evidence_ref": "..."
}
```

Retries upsert the same `(question, passage_id)` history edge. EvidenceSet writes upsert `(evidence_set, passage_id)` and add need links instead of copying the passage. History edges retain `source_attempt_id`; Graph v2 retrieval uses fact validity and canonical source grounding rather than hydrating those edges.

When a question child Attempt is ready, its found frozen EvidenceSet items are
also linked directly to the high-level canonical `KnowledgeQuestion`. One
`expert_knowledge_receipts` row is then written for each `raised_by` and
`assigned_to` relationship. This is durable expert-to-question lineage; Mem0
receives only an idempotent receipt pointing back to it.

Sibling work (evidence quality / source authority, progress events, durable workers) can land later. Reused candidates already re-enter the existing evidence + sufficiency path.
