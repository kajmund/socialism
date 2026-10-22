# Workflow-first execution policy

This is the execution policy for Socialism research and agent work. It is
binding for new orchestration. It does not change today's production
evidence-sufficiency assessor ([PR #420](https://github.com/kajmund/socialism/pull/420)).

Linked from [AGENTS.md](../../AGENTS.md). Experiment guide:
[evidence-sufficiency-experiment.md](../guides/evidence-sufficiency-experiment.md).

## Priority

Every decision uses the cheapest correct layer that can finish the work.
Later layers may run only when an earlier layer cannot decide.

```text
1. Deterministic code
2. Jev (TypeSafe System One)
3. Reusable typed subworkflows
4. Bounded narrative agent
```

1. **Deterministic first.** Schemas, hashes, offsets, aggregation, quality
   gates, and programmatic sufficiency (`can_assess_programmatically`) run
   without a model. If the outcome is determined, stop.
2. **Jev second.** Closed questions with declared choices or noul scores.
   Parallel Jev calls are allowed. Jev does not retrieve, write, or invent
   evidence IDs.
3. **Reusable subworkflows third.** Named, typed, allowlisted workflows
   (segment, evaluate, aggregate, quality gate). They compose. SWE `task` /
   `decision` / `map` / `fork` orchestrate them. SWE `subworkflow` stays
   reserved until the Rust runtime accepts it; the same typed handlers are
   the reusable unit.
4. **Bounded narrative agent last.** A chat-style agent runs only when
   **both** are true:
   - Jev (or deterministic aggregation of Jev verdicts) says a narrative
     pass is necessary.
   - Deterministic quality gates permit it (full coverage, no omitted
     evidence, budget remaining, recursion limit not exceeded).

If a later layer is skipped, the earlier layer's result is the result.
There is no silent downgrade and no alternate model.

## Why this order

PR #420 budgets one Cerebras structured-output call at 60 000 characters.
When the encoded EvidenceSet is larger, passages are trimmed to 1 500
characters and later items are listed as `omitted_evidence` with reason
`assessment_char_budget`. That keeps the production attempt from dying on
`context_length_exceeded`. It also means a 567 k-character EvidenceSet can
be judged from a 56 k-character window. Tail counterevidence and late
items can disappear from the model's view.

Workflow-first treats that windowing as a **measured production
compromise**, not as the execution policy. Complete evidence is the
default for new work. Truncation is never silent: if a budget cannot
cover the work, fail loudly or split the work into typed workflows that
together cover every character.

## Agent tools

Narrative and expert agents may invoke **allowlisted typed workflows
only**. Forbidden as agent tools:

- generic search
- generic database / SQL / session access
- raw HTTP, filesystem, or shell
- unregistered SWE handlers
- another free-form agent (no agent-spawning tool)

Allowlisted names live in
`app.services.research.sufficiency_experiment.tools.ALLOWED_WORKFLOWS`.
An unknown name fails loudly. Recursion through a tool is capped
(`max_narrative_depth`). Each invocation records provenance (workflow
name, input hash, output hash, parent span).

This is the same isolation idea as
[expert-chat-worker-delegation.md](../specs/expert-chat-worker-delegation.md):
workers return structure; the owner decides. Workers here are workflows,
not personas and not research providers.

## SWE / Jev / subagents

| Layer | What exists today | What this policy uses |
| ----- | ----------------- | --------------------- |
| Rust SWE (`crates/swe-native`) | `task`, expression/`provider` `decision`, `fork`, `join`, `map`, `end`. Rejects `wait` and `subworkflow`. | Top-level sufficiency definition: programmatic gate → segment → evaluate → aggregate → quality → optional narrative. |
| Jev (`app/jev/system.py`) | System One HTTP. Research screening, document-property verification, Auto routing. | Passage `EVIDENCE_SCREEN_QUESTIONS` + need `ASSESSMENT_QUESTIONS` / `classify_research_decision`. |
| Subagents | Spec only: read-only workers after Jev says decomposable + parallelizable. | Not a general agent. Bounded narrative is one optional SWE task with allowlisted workflow tools. |

SWE never calls Python while the machine lock is held. Handlers and Jev
run outside that lock. Do not hold a database connection across Jev, SWE
handlers, or narrative completion. See the root AGENTS.md connection rule.

## Contracts every layer must keep

- **Strict prompts.** Experiment prompts are constants in the experiment
  package (not production `prompt_fields`). Production prompts stay in
  the database. No hidden extra instructions at the call site.
- **Schemas.** Jev answers and narrative output validate against declared
  schemas. Invalid payload is an error, not `UNDECIDED`.
- **Provenance.** Every passage keeps `evidence_id`, offsets, and
  content hash. Every verdict keeps the Jev model, latency, and input
  hash. Aggregation cites only IDs that were evaluated.
- **Budgets.** Jev concurrency, timeout, passage size, narrative input
  chars, tool-call count. Exhaustion fails loudly or escalates only
  through the quality gate. It does not drop unread evidence.
- **Recursion limits.** SWE `limits.max_steps` / `max_depth`. Narrative
  depth 1. Typed workflows may not re-enter the narrative agent.

## Production vs experiment

| Path | When | Behaviour |
| ---- | ---- | --------- |
| Production | Default. `LlmResearchAssessor` | Unchanged PR #420 budgeted Cerebras call. |
| Experiment | Explicit `ExperimentResearchAssessor` or `scripts/benchmark_evidence_sufficiency.py` | Complete EvidenceSet, semantic segmentation, parallel Jev, deterministic aggregation, conditional narrative. |

Do not wire the experiment into `build_llm_research_assessor` unless a
later change explicitly asks for that opt-in.

## Invariants (evidence sufficiency)

- A single supporting passage is never sufficient. Mandatory obligations
  come from `ResearchNeed.source_types` / `capabilities`. Unknown
  requirements ⇒ `UNCERTAIN`, never sufficient.
- Relevance, factual support, and completeness are separate. Span
  coverage is not semantic completeness.
- Five items with one `independence_key` are one source.
- A contradiction is preserved. It is not final insufficiency. Resolve
  through a typed subworkflow or stay `UNCERTAIN`. No majority vote.
- Jev routing uses `ASSESSMENT_QUESTIONS` + `classify_research_decision`,
  then a deterministic validator chooses FINISH / RUN_SUBWORKFLOW /
  ESCALATE_NARRATIVE / UNCERTAIN. Prefer subworkflow before narrative.
- Missing evaluations, timeouts, errors, or exhausted budgets ⇒
  `UNCERTAIN` or `FAILED`, never sufficient.
- Execution is `WorkflowRunner.run`. Compiling SWD and then looping in
  Python is forbidden.
- The experiment is a `ResearchAssessor`. It does not replace
  `loop_control` follow-up or completeness.

## Anti-patterns

- `if supporting: sufficient = True`
- `if contradiction: insufficient = True`
- `jev_requires_narrative = any(needs_narrative)`
- Treating scripted Jev scores as live Cerebras/Jev quality
- A second evidence or loop model

## Evidence sufficiency experiment (shape)

Assess the **complete** frozen EvidenceSet on SWE:

1. Group with `group_evidence_for_review`.
2. Segment every source character (no silent drop).
3. `map` passage jobs; each child asks `EVIDENCE_SCREEN_QUESTIONS`.
4. Aggregate obligations + `independence_key`.
5. Jev `ASSESSMENT_QUESTIONS` → validate route.
6. Optional `resolve_conflict` subworkflow, then re-aggregate.
7. Emit `ResearchAssessmentDraft` through `sanitize_assessment_draft`.

Do not silently truncate evidence. A character that was not placed in a
passage is a defect.

## Benchmark

Compare the experiment to the frozen PR #420 Cerebras baseline on the
same golden cases: tail counterevidence, late evidence, and the
567 k-character 33-item payload. Report accuracy, false-sufficient rate,
coverage, latency, and cost. See the experiment guide.
