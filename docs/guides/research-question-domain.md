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

The question DAG executor runs dependency-ready questions in bounded parallel waves. It persists a wave's results only after its worker calls return, then makes newly unblocked questions eligible for the next wave. A worker may return follow-up questions; those become `derived` nodes, inherit the responsible expert by default, and depend on the question whose evidence exposed the gap.

`QuestionResearchWorker` is the integration seam to the existing research engine. It keeps DAG scheduling separate from provider routing, evidence persistence, assessment, and completeness. Product entry points are not switched in this stage, so Expertgranskning and expert chat retain their current behavior and Word cannot start research.

`AttemptResearchQuestionWorker` implements that seam. Each general question gets a `research_question` child Attempt under the DAG's parent Attempt. The child runs the unchanged planner → router → evidence quality → assessment → completeness loop and freezes its own EvidenceSet. `ResearchQuestion.execution_attempt_id` is the durable link to that evidence lineage. A retry reuses a ready child Attempt instead of retrieving again.

Derived runtime needs that the child engine has already researched are materialized as completed `ResearchQuestion` descendants. They keep their runtime-need lineage, inherit the responsible expert, and point to the same child Attempt; the DAG must not execute them a second time.

An unassigned question pauses the graph with `waiting_for_assignment`; the executor never guesses an expert. A worker error marks the affected question failed and stops fail-closed. Cycles and cross-Attempt dependencies are rejected when an edge is created.

## Next stages

1. Match each question to an existing expert competency and invoke the existing expert creator when none matches.
2. Replace Expertgranskning `ResearchNeed` entry points with general questions and aggregate the child EvidenceSets for its frozen panel input.
3. Route expert chat questions through the same engine.
4. Add semantic matching for `KnowledgeQuestion` using the configured vector store.
5. Build neutral document-understanding Q&A during ingest, with PDF text anchors, as another `case_knowledge` source. It has no expert ownership and must not contain risk or problem analysis.

Evidence continues to freeze into an `EvidenceSet` before consumers use it. Comments and Word may receive read-only access to frozen evidence in a later stage, but remain outside research initiation.
