# Question → Evidence graph (v1)

Reusable persistent knowledge for research. This is a seam on the existing engine, not a second research loop.

## Runtime vs persistent

| Layer | What it is | Where it lives |
| --- | --- | --- |
| `ResearchNeed` / `ResearchRuntimeNeed` | One Attempt/wave question plus execution/status/lineage | `research_runtime_needs`, plan snapshots |
| `ResearchNeedExecution` | Running / completed / failed for that need | `research_need_executions` |
| `KnowledgeQuestion` | Canonical persistent question identity | `knowledge_questions` + graph node |
| `ANSWERED_BY` / `BESVARAS_AV` | Question → evidence *reference* | graph edge / `knowledge_question_evidence_links` |
| `ResearchEvidence` / `EvidenceSet` | Source of truth for what an Attempt saw | `evidence_set_items` |

A runtime need may resolve to a `KnowledgeQuestion`. Execution state never moves into the graph. Documents stay in EvidenceSet storage. The graph stores a stable reference, excerpt/locator when useful, provider/provenance, timestamps, and version metadata.

Identity is the existing deterministic `research_question_key` (normalized casefold + whitespace) plus an explicit namespace. Semantic matching is a seam (`QuestionIdentityMatcher`); v1 is exact identity only. If embeddings are added later, persist model / version / dimension together.

## Target flow

```text
ResearchNeed
  → resolve/match KnowledgeQuestion
  → bounded one-hop lookup (Question → ANSWERED_BY)
  → normalize into ResearchEvidence
  → persist reused candidates into EvidenceSet
  → ResearchRouter / providers always run in v1
  → merge: live found hit wins the same evidence_ref; leftover candidates stay
  → idempotent upsert Question + ANSWERED_BY (fresh retrieval only)
  → wave-level evidence quality, then the configured ResearchAssessor / completeness
```

Reuse is candidate retrieval, never automatic truth. Graph code cannot mark a need sufficient. v1 does not skip live providers from a programmatic "found = sufficient" check: production assessment can be an LLM and now also sees evidence quality. A later conservative skip-gate must be tested against that real policy.

## Scope

Namespaces are designed now so later customers do not need an unsafe compatibility fallback.

| Namespace | Key | Who can read |
| --- | --- | --- |
| `public` | `visibility=public`, `customer_id` null | Every kund, and only edges whose provenance is public |
| `tenant:{id}` | `visibility=tenant`, required `customer_id` | That kund only |

Public reuse is allowed only when provenance says `public` (`public: true` or `visibility`/`scope` = `public`). Source type alone is not enough. Private tenant evidence is never written to `public` and is never visible to another customer.

Reuse also has to match the current need:

- `source_type` must be in the current `ResearchNeed.source_types`. A cached `web` hit cannot satisfy a later `swedish_law` need.
- `case_knowledge` edges store `knowledge_case_id` and are only visible to that case.
- Tenant edges store `knowledge_module` and stay inside that module.
- Reused `persistent_knowledge` items are not written back. A cache hit must not refresh `observed_at` or keep an edge `fresh` forever.

## Freshness

Persisted on each edge: `retrieved_at`, `observed_at`, source identity, `freshness`.

| Value | Meaning |
| --- | --- |
| `fresh` | Age is within `RESEARCH_KNOWLEDGE_FRESHNESS_MAX_AGE_SECONDS` |
| `stale` | Age is beyond that window, or the edge was stored as stale |
| `unknown` | No timestamp, or no max-age policy. Do not guess |

Default max-age is unset. Reused candidates are then `unknown` and **cannot** skip live providers. Graph reuse never permanently bypasses providers.

## Graphiti

Core research types do not import Graphiti. `QuestionEvidenceGraph` is the contract. Adapters:

- `SqlQuestionEvidenceGraph` — durable production adapter (`POST /execution/attempts/{id}/research`)
- `GraphitiQuestionEvidenceGraph` — maps domain nodes/edges onto a `GraphitiClient` (official SDK is optional; not required in phase 1)
- `InMemoryQuestionEvidenceGraph` — tests
- `DisabledQuestionEvidenceGraph` — empty lookup / no-op write (test default when no graph is injected)

Lookup is one hop and bounded by `RESEARCH_KNOWLEDGE_LOOKUP_LIMIT` (default 10). No communities, GraphRAG, or multi-hop reasoning in v1.

Graph lookup or write failure falls back to normal provider retrieval / keeps already persisted EvidenceSet items. It must not invent sufficiency or fail the Attempt merely because the graph is down.

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

Retries upsert the same `(question, evidence_ref)` edge. They do not duplicate nodes or EvidenceSet items. Edges store `source_attempt_id` so the current Attempt cannot reuse its own in-flight writes; a later Attempt can.

Sibling work (evidence quality / source authority, progress events, durable workers) can land later. Reused candidates already re-enter the existing evidence + sufficiency path.
