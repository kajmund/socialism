# Research question domain

The research engine distinguishes the question asked in its product context from the reusable legal or factual questions required to answer it.

```text
SpecificQuestion (context-bound)
  -> ResearchQuestion (Attempt-bound DAG node)
       -> KnowledgeQuestion (canonical reusable identity)
       -> raised_by expert(s)
       -> assigned_to expert
       -> dependencies on other ResearchQuestions
       -> evidence through the existing question/evidence graph
```

## Responsibilities

| Type | Responsibility |
| --- | --- |
| `SpecificQuestion` | Stores the question as asked in Expertgranskning, expert chat, or another product surface, together with its context and Run. |
| `ResearchQuestion` | Represents one general question as work inside an Attempt. It carries status, depth, origin, dependencies, and optional lineage back to a legacy runtime need. |
| `KnowledgeQuestion` | Gives equivalent general questions a canonical tenant-scoped identity so evidence can be found again. |
| `ResearchQuestionExpert` | Separates who raised the question (`raised_by`) from the expert responsible for answering it (`assigned_to`). |
| `ResearchQuestionDependency` | Forms an acyclic graph inside one Attempt. Independent questions can later execute concurrently. |

The same `KnowledgeQuestion` may be used by several `SpecificQuestion` rows. Each context keeps its own `ResearchQuestion`, so an assessment made for one clause or conversation cannot silently become the assessment for another.

## Current migration seam

`materialize_runtime_needs_as_questions` converts existing `RuntimeResearchNeed` values into the new domain while preserving requester lineage when the caller can map requester IDs to expert IDs. Missing mappings remain explicit as `unassigned`; they are not silently assigned to an unrelated expert.

This first stage is persistence only. It does not change the current planner, research executor, Expertgranskning, expert chat, or Word add-in behavior. In particular, Word cannot start research.

## Next stages

1. Execute ready nodes in dependency waves and allow evidence assessment to add follow-up questions.
2. Match each question to an existing expert competency and invoke the existing expert creator when none matches.
3. Replace Expertgranskning `ResearchNeed` entry points with general questions.
4. Route expert chat questions through the same engine.
5. Add semantic matching for `KnowledgeQuestion` using the configured vector store.

Evidence continues to freeze into an `EvidenceSet` before consumers use it. Comments and Word may receive read-only access to frozen evidence in a later stage, but remain outside research initiation.
