# Evidence sufficiency narrative pre-check (experiment variant B)

Design for an opt-in comparative experiment on the complete-EvidenceSet
assessor. Variant B adds a bounded narrative review before a `sufficient`
may be fixed. The control remains today's Jev + deterministic gates. Nothing
here is production-wired; the production `LlmResearchAssessor` and
`build_llm_research_assessor` are unchanged.

Related: [workflow-first-execution.md](workflow-first-execution.md),
[reuse-before-new.md](reuse-before-new.md),
[evidence-sufficiency-reuse-audit.md](evidence-sufficiency-reuse-audit.md),
[evidence-sufficiency-experiment.md](../guides/evidence-sufficiency-experiment.md),
[evidence-sufficiency-contradiction-trace.md](../guides/evidence-sufficiency-contradiction-trace.md).

## Problem

The live v1 measurement on the four benchmark cases used complete Jev
coverage (coverage 1.00) but called the narrative model **0 times** in every
case. `narrative` is only reachable after `ESCALATE_NARRATIVE`, and the quality
gate permits escalation only when `allows_sufficient` is already false. A
false-sufficient verdict therefore has no later check.

Recorded live v1 results (`jev-1.13.0`, Cerebras `gpt-oss-120b`; source:
[sufficiency-experiment-live-v1.json](../../backend/tests/integration/baselines/sufficiency-experiment-live-v1.json)):

| Case | Source chars | Independent sources | Live v1 draft | Narrative calls | Pre-check eligible? |
| ---- | -----------: | ------------------: | ------------- | --------------: | ------------------- |
| `tail_counterevidence` | 80 122 | 1 | sufficient (false) | 0 | yes, by size |
| `late_evidence` | 836 514 | 49 | sufficient (false) | 0 | yes, by size and sources |
| `large_567k` | 561 346 | 17 | insufficient | 0 | trigger yes, but the gate already blocks sufficient |
| `short_sufficient` | 62 | 1 | sufficient | 0 | no, below both thresholds |

The other seven golden cases have at most 310 source chars and two independent
sources; they are below both thresholds and/or already blocked by the gate.
Case dimensions above are static fixture properties, not model measurements.

The v1 fixture bound no narrative (`narrative=None`), and on the two traps
the gate allowed `sufficient`, so neither escalation nor a narrative call was
reachable. The contradiction trace adds the reason a flag-driven pre-check
would fail: Jev *saw* the contradicting passage in every
case, but scored `contradicts_current_evidence` at **0.19-0.26** against the
0.6 threshold, because each screen call asks about "other supplied facts"
while only one passage is in view. Aggregation, the gate and `_emit_status`
therefore never see a conflict. The pre-check must not depend on the Jev
contradiction flag; boundary sampling is what puts the signal passage in front
of the reviewer. The trace also shows the next layer: even a correctly flagged
contradiction can be dismissed by `resolve_conflict` when Jev calls the
contradicting passage duplicate or redundant, after which the gate can allow
`sufficient` again. A pre-check that reads excerpts is the check after both
layers.

The two false-sufficient traps are large single-passage and late-multi-source
material. A reviewer that only receives aggregation counters cannot see a
contradiction Jev scored too low. A reviewer that receives a deterministic
boundary sample of the passages can.

Hypothesis: Jev + gates + a bounded narrative pre-check reduces
false-sufficient verdicts on the traps without changing `short_sufficient`,
and with at most one narrative model call per run.

## 1. Trigger

New fields in `ExperimentConfig` (`types.py`). Defaults are initial,
pre-registered hypotheses, not measured values.

| Field | Default | Meaning |
| ----- | ------: | ------- |
| `narrative_precheck` | `False` | Enables variant B. Control stays `False`. |
| `precheck_min_source_chars` | `20_000` | Minimum complete-EvidenceSet excerpt characters. Same quantity as `SufficiencyLoop._source_chars`, not judged chars. |
| `precheck_min_independent_sources` | `3` | Distinct `independence_key` values among `status == "found"` items. Reuses `research/quality.independence_key`; five copies of one source still count as one. |
| `precheck_max_input_chars` | `24_000` | Encoded pre-check payload budget. Separate from `max_narrative_input_chars` (12 000), which stays the ESCALATE-narrative budget. |

The existing `max_narrative_depth = 1` and `max_narrative_input_chars` are not
changed.

The pre-check runs only when **all** of these are true:

```text
config.narrative_precheck
and loop._narrative_rounds == 0                  # max_narrative_depth is 1
and quality.allows_sufficient                    # a sufficient verdict is about to be fixed
and (
    source_chars >= config.precheck_min_source_chars
    or independent_sources >= config.precheck_min_independent_sources
)
```

The predicate is only reachable in a run that has a bound completer; an
enabled pre-check without one is rejected before SWE starts (see
"Verdict semantics").

The size/source condition is necessary but not sufficient. Pre-check is
defined as a review of a would-be `sufficient`; it does not run when the
deterministic gate already refuses sufficient (that is the existing
`ESCALATE_NARRATIVE` path's job). Consequently `large_567k`, which v1 already
routes away from sufficient, does not depend on the pre-check. `tail_counterevidence`
and `late_evidence` are the targets because v1 lets them reach sufficient.

Why the trigger is an OR, and why short/single-source skips:

- Large material triggers even with one source, because `tail_counterevidence`
  is one 80 k-character passage and its trap is at the end.
- Several independent sources trigger even when short, because the failure
  mode can be cross-source synthesis rather than a hidden tail.
- `short_sufficient` (62 chars, one source) is below both thresholds. The whole
  evidence is already in Jev's view; a narrative call would add latency,
  non-determinism and a false-insufficient risk while adding no review value.
  Acceptance explicitly requires it to stay sufficient and to make zero
  narrative calls.
- `later_wave_contradiction` (120 chars, 2 sources) is also below both
  thresholds, but its gate already refuses sufficient, so pre-check is not
  relevant there.

### Composition with `ESCALATE_NARRATIVE`

One narrative budget, two possible entry points; never two calls.

- `_narrative_rounds` remains the single counter, capped by
  `max_narrative_depth = 1`.
- Pre-check is eligible only when `quality.allows_sufficient` is true. The
  same quality decision then has `escalate_permitted == False` by construction
  (`quality_gate` sets escalation only when `not allows_sufficient`), so route
  cannot choose `ESCALATE_NARRATIVE` in that state.
- A pre-check downgrade or failure routes directly to `emit`; route does not
  run, so no escalation can follow.
- A pre-check confirm increments `_narrative_rounds` to 1. If a later change
  ever tried to escalate, both the route validator and `run_narrative`'s depth
  check (`depth >= max_narrative_depth` raises `RecursionLimitError`) refuse.
- When pre-check is skipped (disabled, not eligible, or gate blocks
  sufficient), the narrative budget is untouched, so today's
  `ESCALATE_NARRATIVE` path still gets its one call.

Invariant: at most one narrative model invocation per run in both arms.
Control uses the existing call site; variant shares the budget between
pre-check and escalation.

## 2. SWE shape

Two nodes are inserted between `aggregate` and `route`; the rest of the graph
is unchanged.

```text
prepare -> programmatic_gate --true--> emit
                    |false
                    v
                  jobs -> aggregate -> precheck -> precheck_gate
                                                      |true (downgrade)   |false
                                                      v                  v
                                                    emit               route -> finish_gate -> ...
```

Exact changes in `workflow.py`:

```python
# HANDLER_NAMES gains one entry
"sufficiency.narrative_precheck"

# aggregate.next changes from "route" to "precheck"
"precheck": {
    "type": "task",
    "handler": "sufficiency.narrative_precheck",
    "next": "precheck_gate",
},
"precheck_gate": {
    "type": "decision",
    "evaluator": "expression",
    "condition": {
        "eq": [{"var": "$.precheck.result.downgrade"}, {"const": True}]
    },
    "routes": {"true": "emit", "false": "route"},
},
```

`compile_sufficiency_workflow(concurrency)` keeps its signature and `@cache`
key. The smallest change is one entry in `HANDLER_NAMES`, the two node
entries above, and `aggregate.next` changing to `precheck`. The graph is
shared by both arms; only the config differs. When
`narrative_precheck` is `False`, the handler returns immediately with
`verdict="disabled"` and `downgrade=False`, so control makes no model call and
takes the same branch and status as today. The two extra deterministic nodes
appear in the control trace as skipped, which is the evidence that control did
not review anything.

`SufficiencyLoop` changes, all in `loop.py`:

- Add `self._precheck: NarrativePrecheck | None` and the handler registration
  `"sufficiency.narrative_precheck": self._narrative_precheck`.
- The handler computes the predicate, assembles the payload, calls the
  injected `NarrativeFn` once, sanitizes the returned draft, maps it to a
  verdict, and records the trace. It does not loop and does not re-enter SWE.
- Increment `_narrative_rounds` and `_llm_calls` when the completer is
  invoked, including a call that later times out or fails. Incrementing on the
  attempt is what keeps the one-call invariant true after a failure.
- `_emit_status` applies the veto before its existing sufficient check:
  failed pre-check => `failed`; downgrade => `uncertain`; confirm/disabled/skipped
  => existing logic unchanged.
- `_emit` builds the same deterministic `draft_from_aggregations` draft and
  appends `narrative_precheck_rejected` / `narrative_precheck_failed` to the
  reasons. The reviewer's own draft is never the product draft.
- `_build_report` records `precheck`.

Handler return value (becomes `$.precheck.result`):

```python
{
    "enabled": bool,
    "triggered": bool,
    "ran": bool,
    "verdict": "disabled" | "skipped" | "confirm" | "downgrade" | "failed",
    "downgrade": bool,
    "input_hash": str | None,
    "output_hash": str | None,
    "evidence_fingerprint": str,
    "input_chars": int,
    "included_passage_ids": list[str],
    "omitted_passage_ids": list[str],
    "error": str | None,
}
```

`downgrade` is the only routing field; it is `True` for both `downgrade` and
`failed` (fail-closed) and `False` otherwise. The remaining fields are copied
into `ExperimentReport.precheck` and the artifact trace.

The new report records are thin, report-only types in `types.py`:

```python
PrecheckVerdict = Literal["disabled", "skipped", "confirm", "downgrade", "failed"]

@dataclass(frozen=True)
class PrecheckPassageRef:
    passage_id: str
    evidence_id: str
    selection_reason: str

@dataclass(frozen=True)
class NarrativePrecheck:
    enabled: bool
    triggered: bool
    ran: bool
    verdict: PrecheckVerdict
    input_hash: str | None
    output_hash: str | None
    evidence_fingerprint: str
    input_chars: int
    included_passages: tuple[PrecheckPassageRef, ...]
    omitted_passages: tuple[PrecheckPassageRef, ...]   # selection_reason = omission reason
    omitted_evidence: tuple[tuple[str, str], ...]      # (evidence_id, reason)
    review_result: str | None
    error: str | None
    latency_ms: float
    provenance: tuple[ProvenanceEvent, ...] = ()
```

`ExperimentReport` gains `precheck: NarrativePrecheck | None = None`. The
reviewer's full draft is not kept on the report; the hashes, verdict and
included/omitted refs are enough to audit the veto.

The programmatic path (`programmatic_gate` true) goes straight to `emit` and
never pre-checks. A plan with no needs, or an EvidenceSet with no found item,
is deterministic; deterministic-first wins and no model is called.

No Python orchestration loop is introduced: SWE owns the branch, the handler is
one bounded task, and `WorkflowRunner.run` remains the only runner. The
narrative call is external work inside a handler, so no database session may
be open; `run_experiment` already takes materialized `ResearchPlan` and
`AssessableEvidence`. Any future production wiring must release the input
transaction before the run and persist afterwards.

## 3. What the narrative sees

Payload assembled by `assemble_precheck_payload()` in `narrative.py`, then
passed through the existing `NarrativeFn` completer:

```json
{
  "review_task": "precheck_sufficient",
  "system": "<existing NARRATIVE_SYSTEM_PROMPT, unchanged>",
  "allowed_tools": [], "bound_workflows": [],
  "needs": ["research_need_id"],
  "aggregations": ["<existing narrative._row rows>"],
  "quality": {"span_coverage": 1.0, "reasons": []},
  "evidence": {"fingerprint": "...", "source_chars": 836514, "found_items": 49},
  "passages": [
    {"passage_id": "evidence-48:p0", "evidence_id": "evidence-48",
     "research_need_ids": ["research_1"], "start": 0, "end": 1500,
     "content_hash": "...", "selection_reason": "boundary_head",
     "text": "<whole 1 500-char passage>"}
  ],
  "omitted": {
    "passages": [{"passage_id": "...", "evidence_id": "...",
                  "content_hash": "...", "reason": "precheck_input_budget"}],
    "evidence_items": [{"evidence_id": "...", "reason": "not_found"}],
    "counts": {"candidates": 0, "included": 0, "omitted": 0}
  },
  "max_input_chars": 24000
}
```

No tool is bound: the pre-check gets a single structured completion, not a
tool loop, so `allowed_tools` and `bound_workflows` are empty.

### Deterministic selection

Aggregations are the complete-EvidenceSet summary: every passage Jev judged is
represented there through obligation state, supporting IDs, contradictions and
`missing_or_weak`. Raw text is sampled so the reviewer can inspect material
outside the summary. Selection order is deterministic and budget-aware:

1. **Base.** Needs, aggregations, quality summary and evidence metadata are
   mandatory. If the base alone exceeds `precheck_max_input_chars`, fail loudly
   (`precheck_payload_over_budget`); aggregation rows are never truncated.
2. **Jev-flagged contradictions** (`contradicts_current_evidence >=
   contradict_threshold`), in EvidenceSet order. If they do not fit, fail
   loudly rather than omit a flagged contradiction.
3. **Boundary sample.** Head and tail passage of the first, middle (median) and
   last found item with a non-empty excerpt. This catches the measured traps
   when Jev misses them: `tail_counterevidence` (tail of the only item),
   `late_evidence` (head of the last item), `large_567k` (tail of the first
   found item). `selection_reason` is `boundary_head`, `boundary_tail` or
   `boundary_source`.
4. **Jev-flagged support** (`directly_supports_answer >= support_threshold`),
   in EvidenceSet order.
5. **Spread.** One unused passage from each evenly spaced found item, then
   evenly spaced passages across the remaining concatenated sequence. This
   deterministic stride gives middle material representation instead of
   front-loading the budget. `selection_reason` is `spread`.

Items are added in priority order until the encoded payload would exceed
`precheck_max_input_chars`; the first item that does not fit ends inclusion.
Passages are whole 1 500-char segments; text is never sliced to fit. Passages
from `status != "found"` or empty-excerpt items are not candidates; they are
summarized by aggregations and listed in `omitted.evidence_items` with reason
`not_found` / `no_excerpt`.

### Explicit omission, no silent truncation

Every candidate passage is either in `passages[]` or in
`omitted.passages[]` with a reason; every evidence item is either represented
by an included passage or listed in `omitted.evidence_items`. The payload asserts
`candidates == included + omitted`. The reviewer sees that material was not
shown; a confirmation does not silently imply the omitted material was
reviewed.

### Provenance hashing

- Canonical encoding:
  `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
  applied **after** the included/omitted split is final.
- `input_hash = sha256(canonical_payload).hexdigest()` — any change to
  selection, budget or evidence content changes it.
- `output_hash = sha256(canonical reviewer draft).hexdigest()` over the
  sanitized draft fields that determine the verdict (result, need assessments,
  gaps, contradictions), not only the rationale.
- `evidence_fingerprint = evidence_fingerprint(evidence)` (existing
  `assessment.py` helper) binds the exact EvidenceSet version.
- A `ProvenanceEvent(workflow="narrative_precheck", input_hash=..., output_hash=...,
  parent="sufficiency.aggregate")` is stored in `ExperimentReport.precheck.provenance`.
- The artifact trace gains a `precheck` section with the same hashes plus
  included passages (id, evidence id, selection reason, content hash, text
  joined from `report.passages`) and the omitted list, so the reviewer's view
  can be reconstructed. If the concurrent trace investigation is kept, extend
  `trace.py`; otherwise put the same fields in the benchmark artifact.

## 4. Verdict semantics

The completer returns a `ResearchAssessmentDraft` (the existing narrative
contract). It is passed through
`sanitize_assessment_draft(draft, plan=plan, evidence=evidence)`:

- sanitized `result == "sufficient"` -> `confirm`
- anything else (including a sanitizer downgrade after invented or missing
  IDs) -> `downgrade`
- exception, timeout or an invalid/unusable draft -> `failed`

The pre-check **never upgrades**. It is invoked only when
`quality.allows_sufficient` is already true; its output can keep that verdict
or veto it. It cannot turn a blocked gate into sufficient.

Decision table:

| Gate allows sufficient | Trigger | Reviewer | Route runs? | `ExperimentReport.status` | Product draft |
| ---------------------- | ------- | -------- | ----------- | ------------------------- | ------------- |
| no | not evaluated | not called | today's route/escalate | unchanged (today) | unchanged (today) |
| yes | no | not called | yes | `sufficient` | deterministic sufficient |
| yes | yes | confirm | yes | `sufficient` | deterministic sufficient |
| yes | yes | downgrade | no, emit directly | `uncertain` | `insufficient`, deterministic |
| yes | yes | failed | no, emit directly | `failed` | `insufficient`, deterministic |
| — | payload base or flagged contradictions over budget | not called | no, emit directly | `failed` | `insufficient`, deterministic |

Rules behind the table:

- **The product draft stays deterministic.** The reviewer draft is a veto
  signal, not a competing assessment. On confirm the draft is exactly
  `draft_from_aggregations` as today. On downgrade/failure it is
  `draft_from_aggregations(status="uncertain"|"failed", ...)` with a
  `narrative_precheck_*` reason. The reviewer rationale and findings remain in
  `ExperimentReport.precheck` and the trace; they are not merged into the
  product draft.
- **Route is skipped on veto.** A gate that allows sufficient has no applicable
  subworkflow and no escalation permission, so the Jev route cannot change the
  outcome; running it would only add a misleading `FINISH`. Skipping is
  explicit and recorded (`precheck.verdict`).
- **Failure is fail-closed, not a fallback.** A failed, timed-out or
  invalid pre-check means the run may not emit sufficient; it reports
  `failed` and the draft is insufficient. There is no alternate reviewer, no
  second model, no retry beyond the shared structured completer's one
  documented retry, and no fall-through to the deterministic gate as if the
  review had passed.
- **Unbound.** If `narrative_precheck=True` and no completer is bound, the
  loop/assessor constructor raises before SWE starts. That is a config error;
  silently running the control path would mislabel the arm and hide a missing
  dependency.
- **Timeout.** The completer's configured LLM timeout (and the SWE
  `timeout_seconds` ceiling) governs. `TimeoutError` maps to `failed`.
- **Budget.** A payload that cannot fit the mandatory base or a flagged
  contradiction fails loudly; it does not drop material and pretend to review.

## 5. Reuse-vs-new matrix

Policy: [reuse-before-new.md](reuse-before-new.md). No new framework, runner,
provider, evidence model or gate.

| New unit | Existing counterpart | Decision | Justification if new | Proof |
| -------- | -------------------- | -------- | -------------------- | ----- |
| `precheck` / `precheck_gate` nodes | `workflow.py` SWD (`task`, expression `decision`) | **Extend** | Two nodes in the existing graph; no new node type, no second definition. | `test_sufficiency_experiment_workflow` extended for nodes and handler set |
| `sufficiency.narrative_precheck` handler | `SufficiencyLoop` handler object | **Extend** | Same handler pattern as `_run_narrative`; runs inside `WorkflowRunner`. | Runner test asserts `precheck` node executed; `llm_calls` counted |
| Pre-check pass | `narrative.run_narrative` | **Extend** | Same completer (`NarrativeFn`), same `NARRATIVE_SYSTEM_PROMPT`, same hashing/provenance conventions; new payload assembly only because it includes passages. No new reviewer. | Scripted narrative runs through `NarrativeFn`; same sanitizer |
| Review output | `ResearchAssessmentDraft` + `sanitize_assessment_draft` | **Reuse** | The existing product contract and sanitizer validate IDs; no new verdict schema. | Existing sanitize tests plus a pre-check case with invented IDs |
| Draft construction | `draft_from_aggregations` | **Reuse** | Veto changes only `status`/reasons; rows remain the deterministic aggregation. | Golden control/variant draft comparison |
| Deterministic gate | `quality_gate` / `QualityDecision` | **Reuse, unchanged** | Pre-check is a separate veto; mutating the gate would conflate layers and break existing tests. | Existing gate tests stay green |
| Jev route | `decide_route`, `validate_route`, `classify_research_decision` | **Reuse, unchanged** | Variant changes when route is reached, not what route decides. | Existing route tests stay green |
| Passage source | `segment_evidence` / `EvidencePassage` | **Reuse** | Segments and `content_hash` already exist; pre-check selects, never re-segments. | Selection tests use segmented passages |
| Independent-source count | `quality.independence_key` | **Reuse** | Five copies of one source remain one source; no new identity. | `duplicate_sources` pre-check trigger test |
| EvidenceSet version | `evidence_fingerprint` | **Reuse** | Existing canonical EvidenceSet hash for provenance. | Hash stability test |
| Provenance event | `ProvenanceEvent` | **Reuse** | Same record used by `invoke_workflow`. | Pre-check payload hash recorded |
| Config | `ExperimentConfig` | **Extend** | Four fields on the existing frozen config; no settings/env changes. | Config default tests |
| `NarrativePrecheck` (+ included-passage ref) | `ExperimentReport` wrapper precedent | **New thin report record** | The draft cannot hold hashes, triggers and included/omitted passages; same justification as `ExperimentReport`. Not a domain model. | Trace/report tests |
| Benchmark comparison | `BenchmarkReport` / `PathMetrics` / `_experiment_metrics` | **Extend** | Reuse per-case metrics and reducers; add pre-check counters and a control/variant wrapper. | Scripted control vs variant test |
| Scripted reviewer | `ScriptedSufficiencyJev` precedent | **Test double only** | Deterministic plumbing test; never live-quality evidence. | Scripted benchmark labels `measurement="scripted"` |
| Live reviewer binding | `complete_structured_retry`, `EvidenceSufficiencyModel` | **Reuse + thin adapter** | One adapter builds messages from the payload and validates the existing schema. No new model client or prompt store. | Live path reports `unavailable` without keys; no scripted substitution |
| Production wiring | `build_llm_research_assessor` | **Not touched** | Opt-in experiment only. | Existing production-unchanged test |

`narrative.py` is the right home for payload assembly and verdict mapping; no
new module is needed. The pre-check trace is added to the existing artifact
format rather than creating a second trace format.

## 6. Metrics and acceptance criteria

### Arms

- **control:** `ExperimentConfig()` (`narrative_precheck=False`), today's Jev +
  gates, with the same narrative completer still bound. Narrative remains
  reachable only through the existing `ESCALATE_NARRATIVE` path.
- **variant B:** `replace(control, narrative_precheck=True,
  precheck_min_source_chars=20_000, precheck_min_independent_sources=3,
  precheck_max_input_chars=24_000)`.

Both arms use the same golden case, the same `ResearchPlan`/EvidenceSet, the
same `JevSystemOne` client and the **same `NarrativeFn` object**, and run
through `SufficiencyLoop`/`WorkflowRunner`. The only difference is config, so
the comparison isolates the pre-check policy rather than the presence of a
reviewer. The recorded v1 fixture used `narrative=None`; it motivates the
experiment but is not the control arm. With a reviewer bound, a gate-blocked
case such as `large_567k` may still use its one existing escalation call in
both arms; that call is attributed to escalation, not to the pre-check.

The compare step reuses `run_benchmark` / `measure_live_models` once per arm;
a thin `PrecheckComparison` wrapper holds both reports and prints the
side-by-side table. There is no second runner or benchmark engine.

Scripted and live runs stay separate:

| Run | Jev | Reviewer | Label | Use |
| --- | --- | -------- | ----- | --- |
| scripted | `ScriptedSufficiencyJev` | scripted reviewer (test double) | `measurement="scripted"` | trigger, plumbing, one-call invariant, hashes, trace completeness |
| live | `HttpJevSystemOne` | live structured completer on the configured model | `measurement="live"` | the actual comparison; `unavailable` without keys, never scripted numbers |

The scripted reviewer is not a model and scripted scores are not model quality.

### Metrics

Per case and per arm:

| Metric | Source |
| ------ | ------ |
| `result`, `status`, `accurate`, `false_sufficient` | `ExperimentReport.draft` / existing `PathMetrics` |
| `short_sufficient` outcome | case-specific acceptance |
| `precheck.triggered`, `.ran`, `.verdict` | `ExperimentReport.precheck` |
| narrative calls / LLM calls | `report.llm_calls`; `precheck.ran`/`.verdict` attributes the call to pre-check vs existing escalation; attempts that failed still count |
| pre-check input chars | `precheck.input_chars` |
| included / omitted passage and evidence counts | `precheck` + payload |
| Jev calls | `report.jev_calls` (variant is one lower when route is skipped on veto) |
| latency wall time | `report.latency_ms`; report both arms |
| coverage | existing `report.coverage` (Jev coverage; pre-check does not change it) |
| route choice | `report.route` (None when veto skipped route) |

Trace fields proving what the reviewer saw (existing opt-in trace artifact from
`scripts/trace_evidence_sufficiency.py`):

```text
precheck.verdict / enabled / triggered / ran / error
precheck.input_hash / output_hash / evidence_fingerprint / input_chars
precheck.included_passages[]: passage_id, evidence_id, selection_reason,
                               content_hash, text
precheck.omitted_passages[]:  passage_id, evidence_id, content_hash, reason
precheck.review_result (sanitized draft result)
narrative_rounds, max_narrative_depth
```

The existing trace already records evaluated passages, Jev scores, aggregation,
quality reasons and route. The pre-check section adds what the reviewer was
given and what it returned.

### Pre-declared acceptance criteria

Deterministic tests (must pass before any live run):

1. Control parity: with pre-check disabled and `narrative=None` (the existing
   scripted configuration), all 11 golden cases keep their current status and
   draft; `llm_calls == 0`; `precheck.verdict == "disabled"`. With a reviewer
   bound, control still makes no pre-check call; any call is the unchanged
   escalation path.
2. Trigger boundaries: `tail_counterevidence`, `late_evidence` and
   `large_567k` satisfy the size/source predicate; `short_sufficient` does not;
   five duplicate items with one `independence_key` count as one source.
3. One-call invariant: a run makes at most one narrative call; a pre-check
   confirm plus a forced escalation attempt raises instead of calling twice.
4. Verdict mapping: scripted confirm -> sufficient; scripted downgrade ->
   uncertain/insufficient; scripted failure/timeout -> failed/insufficient;
   invented IDs are sanitized and cannot confirm.
5. No silent omission: `candidates == included + omitted`; over-budget base
   fails loudly; every omitted item has a reason and a content hash.
6. Hash stability: same inputs/config produce the same `input_hash`; changing
   the payload changes it.
7. Control has no reviewer call and variant on `short_sufficient` has none.

Live comparison (pre-declared success criteria, repeated runs because live is
non-deterministic):

1. On the two trap cases (`tail_counterevidence`, `late_evidence`), the variant
   draft is **not sufficient** in every run; control is expected to remain
   false-sufficient from the recorded v1 behavior.
2. `large_567k` has the same draft/status in both arms and `precheck.ran ==
   False` there; any reviewer call is the existing escalation call and is
   identical in both arms.
3. `short_sufficient` remains sufficient in both arms, with zero narrative
   calls in the variant.
4. Variant accuracy is at least control accuracy on the four cases, and
   `false_sufficient_rate` is lower than control.
5. Every variant run makes at most one narrative call; `tail_counterevidence`
   and `late_evidence` show `precheck.ran == True`; `short_sufficient` and
   `large_567k` show `precheck.ran == False`.
6. Pre-check input never exceeds `precheck_max_input_chars`; omitted material
   is explicitly listed in every triggered run.
7. Latency and input-char cost are reported side by side; no hidden retry or
   extra Jev wave is introduced.

If criteria 1-3 fail on the live run, variant B is discarded rather than
loosened into a second reviewer or a wider trigger. Scripted checks are a
precondition, not evidence of model quality.

## 7. Risks and open questions

- **Cost and latency.** One extra structured model call (plus the shared
  completer's single possible retry) on triggered cases. `late_evidence`
  already needed 589 Jev calls and ~41.5 s in the v1 fixture; the reviewer adds
  latency even though its input is bounded. The design intentionally skips
  short/single-source cases to avoid paying this everywhere.
- **Non-determinism.** Live Jev and live narrative both vary. A single run
  cannot accept or reject the variant; repeat runs and report per-run results.
  Scripted results must never be presented as model quality.
- **Database-prompt rule.** `NARRATIVE_SYSTEM_PROMPT` is hardcoded in the
  experiment package. The pre-check reuses it unchanged rather than adding a
  second hardcoded prompt, but this still violates the runtime rule that
  prompts live in `prompt_fields`/`prompt_overrides`. It is an existing
  experiment-only exception, is flagged here, and is **not** expanded: no new
  DB plumbing, prompt key or production prompt is designed in this change.
  Production wiring is blocked until the reviewer prompt is a real prompt
  field.
- **Prompt injection.** Evidence excerpts are untrusted external text and the
  reviewer sees raw passages. The reviewer has no tools, no database, no HTTP
  and returns a schema-validated verdict, so the blast radius is a wrong
  verdict. Because it can only downgrade, injection cannot turn a blocked gate
  into sufficient, but it can defeat the review by making the reviewer
  confirm a false sufficient. The pre-check is an additional check, not a
  security boundary; delimit evidence as data in the payload and keep the
  deterministic gate authoritative.
- **Selection bias and omission.** The reviewer sees aggregation summaries plus
  a deterministic boundary/priority sample, not all 567 000 characters. The
  omitted list makes the gap explicit, but a confirm still does not prove the
  omitted text was harmless. Boundary sampling is a hypothesis about where the
  known traps live; if a trap sits in unsampled middle material and Jev misses
  it, the pre-check will miss it too.
- **Trigger thresholds are unvalidated.** 20 000 chars, 3 sources and 24 000
  input chars are pre-registered starting points, not measured optima. Tuning
  them after seeing live results is a new experiment and must be reported as
  such; otherwise the comparison is p-hacked.
- **Control purity.** Both arms share one compiled workflow, so control traces
  the skipped pre-check node. It is deterministic, makes no model call and
  cannot change status; tests assert parity. If exact historical trace parity is
  required, compile two definitions instead, but that adds a second graph and
  weakens the "same workflow, one config switch" comparison.
- **Route is skipped on veto.** This is safe while `allows_sufficient` implies
  no applicable subworkflow and no escalation. If the gate semantics change,
  revisit whether route must still run for trace or future decisions.
- **Programmatic path bypasses the pre-check.** Deliberate: deterministic-first
  has already decided; no model should be added there.
- **Open question: dedicated reviewer schema.** The design reuses the full
  assessment draft because it already has a sanitizer and matches the existing
  narrative contract. A smaller confirm/downgrade schema would be cheaper but
  would duplicate the product contract and lose per-need findings.
- **Open question: should the reviewer see quality flags and claims?** Current
  payload keeps the material small: aggregations, quality summary and sampled
  passages. Per-item quality flags may help; adding them expands the payload
  and should be measured, not assumed.
- **Why opt-in and unwired.** `build_llm_research_assessor` and
  `LlmResearchAssessor` remain unchanged. The experiment is not imported by
  production modules, has no DB prompt, no session and no worker integration.
  It becomes a candidate for wiring only after repeated live runs show fewer
  false-sufficient verdicts without `short_sufficient` regressions, and after
  the DB prompt rule is satisfied.

No hard constraint makes variant B impossible. The binding constraint is the
DB-prompt rule: it blocks production wiring, not the opt-in experiment.
