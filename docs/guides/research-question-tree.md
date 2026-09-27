# Recursive research question tree

Attempt research without an explicit `ResearchPlan` starts from one persisted root
question. Jev scores two orthogonal decisions before retrieval. Program code
applies `research_question_atomicity_threshold` to both and chooses the action.

**Researchability** asks whether the question can be sent to retrieval now as
one bounded evidence need and still produce a grounded answer. Many sources,
cases, studies, or positive and negative findings can still be one need.

**Decomposability** asks whether a robust answer naturally consists of several
distinct substantive conclusions that can be researched and grounded separately,
even when every part concerns the same subject. Separate does not mean
unrelated. Evidence-object count, result count, opposite outcomes of one
component, a paraphrase, and question length are not a split.

| Researchability | Decomposability | Action in this version |
| --- | --- | --- |
| researchable | not decomposable | retrieve |
| researchable | decomposable | decompose, and keep `researchability=researchable` |
| not researchable | decomposable | decompose |
| not researchable | not decomposable | `unresolved` |

A clear `decomposable` decision is split even when researchability is
`uncertain`. Uncertain decomposability does not split a researchable question;
that question is retrieved. Any other uncertain pair stays `unresolved`.

A researchable and decomposable parent is decomposed so the tree records its
knowledge dimensions. This version does not retrieve that parent in parallel
with the children. The persisted researchability is what a later frontier step
will use.

Program code then asks Jev, one candidate at a time, whether a complete
answer to that child would answer the whole parent, an already accepted
sibling, or an ancestor. A proper substantive subset is a valid child.
Parent containment does not reject that child: either subset signal at the
threshold accepts it. A paraphrase that still asks the whole question, with
both subset signals below the threshold, is `redundant_with_parent`. A
subset of an ancestor is allowed; the same whole question as a sibling or
ancestor is not. Reasons are `redundant_with_parent`,
`redundant_with_sibling`, `redundant_with_ancestor`, and
`not_distinct_knowledge_need`. Rejected candidates are not created.
Candidates dropped before that score — empty text, a duplicate, or the
child budget — are `pre_filtered`. Every proposal is one of accepted,
rejected, or pre-filtered. The surviving set is accepted when it shows
semantic progress, would help answer the parent, and is not mainly
paraphrase (`research_question_decomposition_threshold`). `independent`
and `narrower` are recorded and do not reject the set on their own.
A rejected split does not fail the node. `question_decomposed` records
`decomposition_decision`: `accepted` when at least two distinct children
remain, `insufficient_distinct_children` when only one remains, and
`no_valid_children` when none remain. Fewer than two valid children is
semantic exhaustion (`decomposition_result=exhausted`). Researchability is
left as scored. The same question is retrieved
(`execution_override=best_effort_retrieval`,
`generated_from=decomposition_fallback`). That is an execution decision, not
a technical failure. A provider timeout, invalid model output, or other
exception follows the normal failure policy and does not start retrieval.
An exhausted node is not decomposed again in the same evaluation. One
accepted candidate is not persisted as a single-child chain.

Retrieval leaves are nodes with phase `ready` that are researchable, nodes
with `execution_override=best_effort_retrieval`, or nodes that already have
a research need. A decomposable parent that still has children is not
retrieved in this version. At `max_question_depth` a researchable node is
retrieved; any other node stays `unresolved` with reason `max_depth`. The
guardrail defaults to depth 10 and does not rewrite decomposability. The
`atomicity` column remains on the node and is not the execution source of truth.
Research normally stops because a parent answer is sufficient, a remaining gap
is immaterial, or more research would not change the answer. Descendants that
were never needed are `not_required`. `failed` is reserved for technical
failures. A parent answer links only to the child-answer versions that were
used, so an unfinished descendant can remain while the parent is answered.
The `question_tree_shape` event records depth distribution, branching, and how
many parents were synthesized before every descendant was finished.

## Persistence

`research_question_nodes` is an SQL adjacency list scoped to an Attempt.
`parent_question_id` supports both parent-to-child and child-to-parent traversal.
Each node stores `researchability` and `decomposability`
(`researchable` / `not_researchable` / `uncertain` / `pending`, and
`decomposable` / `not_decomposable` / `uncertain` / `pending`) plus the NOUL
subset for that decision. The canonical `knowledge_question_id` remains the
reuse seam.

Answers are immutable rows in `research_question_answers`. A node's
`current_answer_id` changes only when answer text or direct provenance changes.
Controller phases, completeness, and NOUL values stay on the node and in progress
events; they do not create answer versions.

Provenance is relational:

- parent answer to the exact child-answer versions used for synthesis;
- leaf answer to EvidenceSet items and their passages;
- no copied descendant evidence closure on live parent answers.

The existing frozen EvidenceSet remains the materialized execution snapshot.

## Execution

The tree loop is iterative and resumes persisted nodes after worker reclaim.
Decomposition is idempotent: persisted children are reused. A node already
`unresolved` is not decomposed again. Depth, children, and total question limits
prevent recursive explosion.

In-flight phases (`assessing_atomicity`, `researching`, `synthesizing`,
`assessing_completeness`) are resumable. `synthesizing` with no current answer
runs synthesis again, and the new answer version, `current_answer_id`, and the
next phase commit together. When the Attempt itself fails, those nodes are
marked `failed`. That is an execution failure. `insufficient_evidence` remains
a knowledge gap and may still finish the product DAG as `completed_with_gaps`.
An exception, timeout, or invariant failure must not.

Parent completeness sees answered children and terminal siblings that have no
grounded answer (`unresolved`, `not_required`, `failed`). `not_required` does
not count as an unresolved knowledge need and does not block the parent.
When the attempt finishes, a required node that is still waiting and has no
answer becomes `unresolved`. A root with no grounded answer and unresolved
required descendants is not a successful completion.

An evidence gap does not rewrite researchability or decomposability on the
parent. After synthesis, Jev may identify a material gap. The LLM then
formulates gap questions, and program code validates and persists them as
normal child nodes. They pass through the same structure decision and the same
leaf execution path.

Provider adapters, bounded need concurrency, per-need timeouts, knowledge reuse,
EvidenceSet persistence, and fail-close behavior are unchanged.

Synthesis of independent siblings is still depth-ordered: A finishes before B
starts. The next execution step is readiness-driven. When A's children are
ready, A can be synthesized while C is still researching. The parent becomes
runnable when its dependencies are ready, not when a walk reaches it.

## Progress and observability

Question lifecycle events are committed with the domain state and published only
after commit. Completed steps include `duration_ms`; Jev and generative steps also
include model identity. Correlation fields include Attempt, question, parent,
depth, and need execution identifiers.

The research overview projects both the existing product question DAG and
`question_nodes`. The frontend uses the tree projection when present.
