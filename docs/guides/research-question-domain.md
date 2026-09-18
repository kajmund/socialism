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

`QuestionResearchWorker` is the integration seam to the existing research engine. It keeps DAG scheduling separate from provider routing, evidence persistence, assessment, and completeness. Expertgranskning is the first product entry point: its experts propose general questions, the moderator consolidates them, and the DAG executes them before the panel starts. Word cannot start research.

`AttemptResearchQuestionWorker` implements that seam. Each general question gets a `research_question` child Attempt under the DAG's parent Attempt. The child runs the unchanged planner → router → evidence quality → assessment → completeness loop and freezes its own EvidenceSet. `ResearchQuestion.execution_attempt_id` is the durable link to that evidence lineage. A retry reuses a ready child Attempt instead of retrieving again.

Derived runtime needs that the child engine has already researched are materialized as completed `ResearchQuestion` descendants. They keep their runtime-need lineage, inherit the responsible expert, and point to the same child Attempt; the DAG must not execute them a second time.

An unassigned question pauses the graph with `waiting_for_assignment`; the executor never guesses an expert. A worker error marks the affected question failed and stops fail-closed. Cycles and cross-Attempt dependencies are rejected when an edge is created.

Before execution, `assign_unowned_research_questions` resolves every unassigned question against the customer's expert Personas. `PanelCompetencyQuestionMatcher` reuses the panel's evidence-free competency gate: profile versus question only. It evaluates all candidates in parallel, removes candidates without actual domain competence, and selects the remaining expert with the highest 0–100 competence score. Ties retain deterministic catalog order. It checks no evidence and cannot assign an expert outside the customer's catalog. If no existing expert is competent, `UnderlagExpertCreator` reuses the existing structured expert-profile generator, persists a customer-scoped expert Persona with `origin=research_auto`, and assigns it to the question. The newly created Persona is immediately available when later questions in the same batch are matched.

Assignment never rewrites provenance. A question must already have at least one `raised_by` expert; otherwise matching fails. The selected or created Persona is added only as `assigned_to`. Persona IDs are the canonical expert identity for this flow, which also makes an automatically created expert available to expert chat later.

## Expertgranskning integration

The web Expertgranskning flow creates one context-bound `SpecificQuestion` for the review and one `ResearchQuestion` per consolidated general question. Every proposing panel expert is preserved as `raised_by`; assignment then independently selects or creates the competent `assigned_to` expert.

Dependency-ready questions execute in parallel through `AttemptResearchQuestionWorker`. When the DAG is complete, the parent `generic_panel` Attempt receives a new frozen aggregate EvidenceSet copied from the child Attempts. Each aggregate item preserves its original evidence identity and records both `research_question_id` and `research_question_attempt_id` in provenance. The panel only starts after this aggregate is frozen and therefore cannot perform ad hoc research or use live expert tools.

An empty expert research plan is valid when the document itself is sufficient. The parent still receives an empty frozen EvidenceSet, making the no-research decision explicit and keeping the final panel on the same immutable-input path.

## Expert chat read-through

Library expert chat performs a read-only semantic lookup against tenant and public `KnowledgeQuestion` identities before answering. Exact identity is checked first; an exact miss uses the configured vector store, while SQL remains authoritative for which questions belong to the namespace. Only links backed by an Attempt in `ready` or `completed` state and an attached frozen EvidenceSet are exposed to the chat model. Case-scoped evidence is excluded because a library chat has no document case context, and another tenant's evidence can never match.

Matching frozen evidence is added to the expert's system context with stable `[R1]`, `[R2]` references and explicit freshness. The expert must disclose gaps or stale evidence rather than invent an answer. This seam creates no Run, Attempt, question, or provider request. Both REST and streaming chat use the same read-through behavior; Word remains outside it.

When the frozen read-through is insufficient, a library expert can offer to start research. This is an explicit two-turn protocol: the expert first asks the user and states what should be researched; only a later affirmative user message unlocks the native `start_research` tool. The server validates both turns instead of trusting the model prompt alone.

The tool creates an `expert_chat_research` Job and returns immediately. The user's original chat question becomes the context-bound `SpecificQuestion`; the standalone question proposed by the expert becomes the initial general `ResearchQuestion`. Its background worker creates the parent Attempt and preserves the initiating expert as `raised_by`. Normal expert assignment then selects or creates the responsible expert before the existing question DAG runs through planning, routing, frozen evidence, assessment and completeness. The chat does not wait for the result or claim that it already exists. Word has neither this tool nor this initiation path.

When the child Attempt has frozen its evidence, found items are published as
`ANSWERED_BY` links on the canonical high-level question. Each expert in the
question lineage receives a durable `ExpertKnowledgeReceipt` and an idempotent
Mem0 receipt. The receipt means “this expert received research for this
question”; it does not duplicate or replace the shared evidence.

## Next stages

1. Surface completed expert-chat research proactively in its originating conversation.
2. Build neutral document-understanding Q&A during ingest, with PDF text anchors, as another `case_knowledge` source. It has no expert ownership and must not contain risk or problem analysis.

Evidence continues to freeze into an `EvidenceSet` before consumers use it. Comments and Word may receive read-only access to frozen evidence in a later stage, but remain outside research initiation.
