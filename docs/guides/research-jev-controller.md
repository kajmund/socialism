# Research Jev fast controller

Jev is a bounded System One control layer in front of the expensive research
assessor and completeness reviewer. It does not replace retrieval, planning,
follow-up question writing, legal extraction, or expert reasoning.

Default: **off**. When enabled without `TYPESAFE_API_KEY`, it stays off. When
enabled with a key, the default mode is **shadow**: Jev runs, the current LLM
path still runs, and ELK records the comparison.
The recursive objective-to-question-tree path requires Jev and fails before
claiming the Attempt when it is unavailable; explicit `ResearchPlan` execution
continues to use the existing optional gates.

## Recursive question decisions

The question tree uses Jev before retrieval for researchability and
decomposability, before parent synthesis for readiness, and after synthesis for
completeness. Jev emits only NOUL signals. It does not emit a combined
atomic/composite verdict. Generative models formulate child questions and
answer text; program code applies thresholds, validates limits, and persists
state.

Researchability signals are `bounded_for_evidence_retrieval` and
`can_produce_grounded_answer`. Both must clear the high band for
`researchable`. Either at or below the low band is `not_researchable`.
Otherwise the decision is `uncertain`.

Decomposability signals are
`robust_answer_requires_multiple_distinct_subconclusions` and
`subconclusions_can_be_researched_separately`. Both must clear the high band
for `decomposable` (`multiple_distinct_researchable_subconclusions`). The
components may concern the same subject; separate does not mean unrelated.
A low score on the first signal is `not_decomposable`
(`single_conclusion_or_mapping`): one conclusion or one mapping, however many
sources, cases, studies, or list items support it. A low score on the second
is `subconclusions_not_separately_researchable`. Positive and negative findings
of the same component stay one question, and a more specific wording of the
parent is not a split. Question length does not decide.
`subconclusions_would_be_useful_as_reusable_knowledge` is logged and does not
decide on its own.

Jev does not write the child questions. After the generator, Jev classifies
each candidate against the parent, accepted siblings, and ancestors
(`same_knowledge_need_as_parent`, `same_knowledge_need_as_sibling`,
`same_knowledge_need_as_ancestor`, `candidate_adds_distinct_subconclusion`,
`candidate_is_narrower_but_substantively_distinct`). Program code drops
reformulations before the set-level progress check, and applies the
decomposition threshold to both. The completed structure event keeps the event
type `question_atomicity_completed` and records both decisions, their reasons and
confidences, the action, and every underlying NOUL.

An evidence gap is not a structure decision. When completeness identifies a
material gap, a separate generator proposes gap questions and code sends each
accepted question through the same structure pipeline.

## Insertion points

1. Programmatic assessment/completeness (unchanged).
2. `GatedResearchAssessor` / `GatedResearchCompletenessReviewer` in
   `app/services/research/fast_gate.py`.
3. Wired only from `build_llm_research_assessor` and
   `build_llm_research_completeness_reviewer`. Direct `LlmResearchAssessor`
   construction in tests is unchanged.
4. `execute_attempt_research` binds correlation IDs and emits
   `research.execution.summary`.
5. System One HTTP lives in `app/jev/system.py`, not `app.llm`, so the
   research package stays free of chat-LLM imports.

## Config

See `docs/guides/backend-setup.md` for `RESEARCH_JEV_*`. Jev research settings
are separate from Auto prompt-selection (`JEV_*`).

## Evaluation reuse

System One calls go through `app/jev/service.py`. A successful, schema-valid
result is stored as `jev_evaluation_artifacts` under a SHA-256 of the
evaluator id and version, model, model config, questions, normalized state,
content hashes, policy version, and security scope. The same key in the same
scope reuses that artifact and does not call Jev again. A changed claim body,
document version, question wording, threshold, or model is a new key.

Reuse does not cross security scopes. Two customers with the same text get
two artifacts. Timeouts, transport errors, and schema failures are not stored.

Concurrent callers with the same key share one outbound call in the process.
A second process that loses the insert reads the row that won the unique
constraint on `(security_scope, evaluation_key)`. Cancelling one waiter does
not cancel the shared call.

`jev_call_count` counts outbound calls. The execution summary also reports
`jev_evaluation_requested_total`, `jev_evaluation_executed_total`,
`jev_evaluation_reused_total`, `jev_evaluation_singleflight_join_total`, and
`jev_evaluation_failed_total`, plus queue, lookup, single-flight, HTTP,
parse, and persist durations. Graph revalidation adds candidate, skipped,
and evaluated counts.

The HTTP client is created at application start and closed on shutdown.
Call sites can still inject a client in tests.

## ELK events

All events use `event.dataset = socialism.research` and structured fields, not
message-string parsing.

| Event | When |
| --- | --- |
| `research.jev.assessment.started` / `.completed` / `.failed` | Assessor gate |
| `research.jev.completeness.started` / `.completed` / `.failed` | Completeness gate |
| `research.jev.evidence_scored` | Per-item shadow screen |
| `research.jev.shadow_comparison` | After the current LLM decision exists |
| `research.jev.short_circuit` | Active mode actually skipped an LLM call |
| `research.execution.summary` | Attempt research finished |

Correlation fields when known: `run.id`, `attempt.id`, `research.question_id`,
`research.child_attempt_id`, `research.need_id`, `customer.id`,
`research.module`, `research.wave_number`, `trace.id`.

Jev errors are categorized (`timeout`, `auth`, `rate_limit`, `invalid_response`,
`schema_validation`, `transport`, `unknown`) and always fall back to the current
LLM path.

Info events log IDs, hashes, counts, source types, probabilities, and latency.
They do not log full evidence, document text, or prompts.
