# Research progress events

## Question-tree events

Recursive research emits committed lifecycle events for question creation,
structure, decomposition, retrieval, synthesis, completeness, and gap expansion.
Payloads carry `question_id`, `parent_question_id`, `depth`, and the need execution
identifier where applicable. Completed steps carry `duration_ms`; model-backed
steps also carry model identity. These events remain projections: question-node,
answer-version, and provenance tables are the source of truth.

`question_atomicity_completed` is the structure event. It records boolean
`researchable` and `decomposable`, nested `researchability` and
`decomposability` objects (`decision`, `reason`, `confidence`), `action`
(`retrieve`, `decompose`, or `unresolved`), `thresholds.structure`, and every
underlying NOUL. Filter `researchable=true` and `decomposable=true` together
for questions that were both directly researchable and split into knowledge
dimensions. Researchability reasons include `bounded_evidence_retrieval`,
`not_bounded_for_retrieval`, and `unresolved_researchability`. Decomposability
reasons include `multiple_distinct_researchable_subconclusions`,
`single_conclusion_or_mapping`, `subconclusions_not_separately_researchable`,
and `unresolved_decomposability`. The logged decomposability signals are
`robust_answer_requires_multiple_distinct_subconclusions`,
`subconclusions_can_be_researched_separately`, and
`subconclusions_would_be_useful_as_reusable_knowledge`.

`question_decomposed` records `parent_question_id`, `child_count`, `decision`
(`accepted` or `rejected`), and `rejection_reason`. It also records
`candidate_count`, `accepted_count`, `rejected_count`, parallel
`rejection_questions` and `rejection_reasons` lists, and
`decomposition_decision` (`accepted`,
`insufficient_distinct_children`, `no_valid_children`, or
`insufficient_semantic_progress`). `pre_filtered_count`,
`pre_filtered_questions`, and `pre_filtered_reasons` record candidates
dropped without a redundancy score (`empty`, `duplicate`). `child_budget`
is the remainder after the parent already has its maximum number of
accepted children. A rejected candidate does not consume that slot.
`candidate_count = accepted_count + rejected_count + pre_filtered_count`.
`validation` carries `independent`,
`narrower`, `semantic_progress`, `paraphrase_risk`, and
`jointly_sufficient_or_useful` when the surviving set was checked.
Acceptance uses semantic progress and joint usefulness at the
decomposition threshold, and paraphrase risk at or below the
complementary band. `independent` and `narrower` do not reject the
set by themselves. A rejected split includes `fallback=best_effort_retrieval`,
`decomposition_result=exhausted`,
`execution_override`, `execution_override_reason`, and `rejection_counts`.
Researchability on the node is unchanged.

`question_tree_max_depth_reached` records a node that hit the hard depth
guardrail. A researchable node is retrieved (`fallback=research_parent`).
Any other node becomes `unresolved` and is not a technical failure.
Decomposability is left as assessed. The payload includes the question, node
and parent IDs, depth, reason `max_depth`, both decisions, and both NOUL maps.

`question_tree_shape` records the attempt's depth distribution, branching, and
how many branches were left unresolved, not required, or failed.
`decomposable_count`, `researchable_count`, and
`researchable_and_decomposable_count` are the structure counts.
`composite_count` mirrors `decomposable_count`.

Persisted `ResearchProgressEvent` rows are an **audit/projection** of Attempt research. Domain tables stay authoritative.

```text
durable state transition
        │  same transaction
        ▼
ResearchProgressEvent  (sequence, type, small payload)
        │  after commit only
        ▼
schedule in-process WebSocket fan-out   ← best-effort, at-least-once
        │  never blocks or fails research
        ▼
GET /execution/attempts/{id}/progress-events?after_sequence=N
```

Live delivery is not the source of truth. A hung or failed socket cannot roll back research; catch-up is the reconnect path. Clients dedupe by event id / sequence. There is no exactly-once bus.

`/ws/research` authenticates, then **subscribes before the persisted replay snapshot**, so a transition committed in that window is delivered live (and may also appear in replay). Clients treat that as at-least-once.

## Why this transport

`main` already has in-process WebSocket hubs (`EventHub` for jobs/reports, room registries for run/panel/Word watch). Research uses the same seam: an attempt-scoped registry + `/ws/research`. No new SSE stack.

The durable background worker (`research_worker.py`) calls the same `execute_attempt_research` on its own sessions. Domain transitions emit `ResearchProgressEvent` there; claim/lease/heartbeat rows do not. There is no HTTP request context on that path.

## Payload rules

Events reference existing IDs (`research_need_id`, `need_execution_id`, `evidence_item_id`, assessment/completeness ids). They do not copy full evidence/documents, prompts, or chain-of-thought. User-visible rationale may appear as a short preview.

## Example stream (one Attempt)

Successful single-need run with an explicit objective + plan:

1. `objective_accepted`
2. `initial_plan_accepted`
3. `research_need_planned`
4. `need_queued`
5. `need_running`
6. `evidence_found` (or `evidence_not_found` / `evidence_error`)
7. `need_completed`
8. `local_assessment_persisted`
9. `global_completeness_persisted`
10. `research_frozen_ready`

A follow-up wave inserts `follow_up_need_derived` + another queued/running/evidence/completed cycle before the next assessment. A global-completeness cycle inserts `global_need_derived` (or `capability_unavailable` when the gap is not executable). Provider/worker failure emits `need_failed` then `research_failed`. Lease loss, reclaim, and shutdown do not fail-close: a fenced or cancelled worker must not emit `research_failed` (or a second `research_frozen_ready`) while another worker still owns the Attempt.
