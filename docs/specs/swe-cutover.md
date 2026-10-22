# SWE research cutover — implementation plan

**Status:** **Executed** (2026-10-22). The two-step cutover is complete; this
document is kept as the execution record.
**Execution:** step 1 parity-PR [#412](https://github.com/kajmund/socialism/pull/412);
measurement v2 [#413](https://github.com/kajmund/socialism/pull/413); step 2
delete-PR [#414](https://github.com/kajmund/socialism/pull/414).
**Base:** `feat/research-baseline-harness`, commit `a17fb55a` (#408 → #409 stacked).
**Deliverable:** executed cutover record. No production code is changed by this
document itself.
**Prerequisites:** measurement gate (task-4) completed and the winning workflow
recorded, #408/#409 merged, CI green.

Line numbers are from `a17fb55a`. Re-check them immediately before the
delete-PR; stacked merges shift them. Function names are the stable key.

## 1. Target end state

One production path, one loop implementation:

```
POST /execution/attempts/{id}/research
  -> accept_attempt_research          app/services/research_worker.py:112
  -> research-research claims (CAS lease)
  -> run_research_claim               app/services/research_worker.py:163
  -> _execute_claimed_research        app/services/research_worker.py:318
  -> execute_attempt_research         app/services/research/execution.py:1111
       prelude unchanged (objective/start/plan/claim/inventory/snapshots)
  -> _run_research_loop               app/services/research/execution.py:992  (thin seam)
  -> swe_bridge.run_research_loop_via_swe
       SWE: run_wave -> map(execute_need) -> finish_wave -> decision -> loop
  -> bridge calls the same research wave primitives as today
  -> freeze / ready                   unchanged, inside finish_wave
```

Other callers of `execute_attempt_research` inherit the bridge with **no
changes**: `app/services/research/question_attempt_worker.py:73`,
`app/services/workspace_research_job.py:93`, and the baseline harness
`backend/scripts/benchmark_research_loop.py:287`.

SWE owns: wave loop, need fan-out (`map`), loop-back routing (`decision`),
bounded concurrency, cancellation of in-flight handlers, durable run/event log.

Research keeps: planning, objective/plan snapshots, need execution internals,
router/providers, evidence persistence, quality, assessment, completeness,
follow-up planning, freeze, progress events, leases, DB schema.

## 2. Removed vs kept

### 2.1 `backend/app/services/research/execution.py`

| Function | Lines | Action |
| --- | --- | --- |
| `_run_need_executions` | 402-452 | **Delete.** Replaced by the SWE `map`; current `execute_one_need` keeps the per-need body. `_complete_timed_out_need` is called from the bridge child handler. |
| `_execute_one_need` | 307-400 | Keep, rename public `execute_one_need`. |
| `_complete_timed_out_need` | 455-500 | Keep, rename public `complete_timed_out_need`. |
| `_pending_need_pairs` | 595-601 | Keep, rename public `pending_need_pairs`. |
| `_runtime_plan` | 603-605 | Keep, rename public `runtime_plan`. |
| `_quality_descriptors` | 608-617 | Keep, rename public `quality_descriptors`. |
| `_run_research_loop` | 992-995 | **Keep**; it becomes the live call seam (body switches to the bridge in the parity-PR, see §6). It is not dead code. |
| `_retrieve_need` | 286-302 | Keep. Used by `need_retrieval.py:33`. |
| `_assert_need_barrier` | 685-706 | Keep. Called by `finish_wave`. |
| `_assess_persisted_evidence` | 620-683 | Keep. Called by `finish_wave`. |
| `_emit_seeded_runtime_needs` | 502-516 | Keep. Prelude. |
| `assessable_from_item` | 518-568 | Keep. Domain helper. |
| `_loop_limits` | 570-592 | Keep. Prelude. |
| `_freeze_ready_attempt` | 709-751 | Keep. Called by `finish_wave`. |
| `_plan_and_persist_follow_ups` | 753-837 | Keep. Called by `finish_wave`. |
| `_review_and_persist_completeness` | 839-913 | Keep. Called by `finish_wave`. |
| `_plan_and_persist_global_needs` | 915-990 | Keep. Called by `finish_wave`. |
| `_write_fence`, `_raise_if_write_fenced` | 239-246 | Keep. Lease/write boundary; see §4. |
| `execute_attempt_research`, prelude helpers, `_refresh_caller_state`, `_bind_attempt_log_context` | 998-1352 | Keep. Only the loop call and its kwargs change. |

### 2.2 `backend/app/services/research/loop_control.py`

| Code | Lines | Action |
| --- | --- | --- |
| `run_research_loop` (the `while True` wave loop) | 126-164 | **Delete.** SWE owns the loop after the parity-PR wired the bridge; this function becomes unreachable and must not survive as a dual runner. |
| `_finish_research_wave` | 167-224 | Keep, rename public `finish_research_wave`. It is the unchanged wave body: barrier → quality → assessment → loop state → decision → follow-up/freeze. |
| `ResearchLoopConfig` | 58-76 | Keep, rename public `ResearchWaveConfig` (it describes one wave step, not a loop). |
| `_loop_config` | 78-80 | Keep, rename public `wave_config_from_kwargs`. |
| `stop_and_freeze` | 83-106 | Keep (private to this module). |
| `advance_research_wave` | 108-123 | Keep (private). |
| `_decide_research_wave` | 226-282 | Keep (private). |
| `_plan_follow_up_or_stop` | 284-326 | Keep (private). |
| `_continue_after_completeness` | 328-403 | Keep (private). |

After deleting `run_research_loop`, remove its now-unused imports in
`loop_control.py:1-52`: `_run_need_executions`, `_pending_need_pairs`,
`EagerQualityBind`, `BindAttemptRelevance`-only imports, `INITIAL_RESEARCH_WAVE`,
`bind_log_context`, `replace`. Run `ruff check` and let it name the exact set.

Keep the file name `loop_control.py` in the delete-PR. Renaming it to
`wave.py` is a separate, optional cleanup PR: a rename makes the diff harder to
review during a cutover.

## 3. Public seams to lift (parity-PR)

The bridge must stop importing private names. Lift exactly these; no new
module and no duplicated domain logic.

| Today (private) | Public name | Home | Consumers after cutover |
| --- | --- | --- | --- |
| `_pending_need_pairs` | `pending_need_pairs` | `research/execution.py` | `swe_bridge._run_wave` |
| `_runtime_plan` | `runtime_plan` | `research/execution.py` | `swe_bridge._run_wave` |
| `_quality_descriptors` | `quality_descriptors` | `research/execution.py` | `swe_bridge.SweResearchLoop.__init__` |
| `_execute_one_need` | `execute_one_need` | `research/execution.py` | `swe_bridge._execute_need` |
| `_complete_timed_out_need` | `complete_timed_out_need` | `research/execution.py` | `swe_bridge._execute_need` |
| `_finish_research_wave` | `finish_research_wave` | `research/loop_control.py` | `swe_bridge._finish_wave` |
| `ResearchLoopConfig` | `ResearchWaveConfig` | `research/loop_control.py` | bridge type + `execute_attempt_research` kwargs |
| `_loop_config` | `wave_config_from_kwargs` | `research/loop_control.py` | `swe_bridge.build_loop` / public runners |

Rules:
- Renames are mechanical; bodies stay byte-identical. `git log -M` must show
  renames, not rewrites.
- Do not move the functions in this PR. `execution.py` already holds the
  prelude and most of the wave body; moving `execute_one_need` out would create
  a diff that hides behaviour changes.
- `tests/test_research_need_timeout.py:26` imports `_complete_timed_out_need`;
  update it to the public name in the same commit.
- Update the bridge imports (`swe_bridge.py:38,53,104,140,158,201,223,243,251`)
  and its docstring. Public names keep `__all__`-free modules as today.

## 4. Cancel, lease-lost and write fence

### Today

- `research_worker._heartbeat_lease` (research_worker.py:301) sets
  `lease_lost` and cancels the execute task when lease renewal fails.
- `execute_attempt_research` installs the fence contextvar:
  `_write_fence.set(lease_lost)` (execution.py:1183), resets it in `finally`
  (execution.py:1283-1284).
- `_raise_if_write_fenced` (execution.py:242-246) raises `CancelledError` at
  every write boundary (execution.py:353, 363, 381, 472, 715).
- `_execute_one_need` re-raises `CancelledError` without marking the need
  failed (execution.py:350-353), so the lease/lost work stays recoverable.
- `execute_attempt_research` re-raises `CancelledError` and converts a set
  fence into `CancelledError` (execution.py:1247-1255). The worker treats
  lease-lost cancellation as a no-op (research_worker.py:202-216).

### Coupling plan (parity-PR)

1. `execute_attempt_research` passes `lease_lost=lease_lost` into the loop
   kwargs (new key at execution.py:1217-1239). The bridge pops it before
   building `ResearchWaveConfig`.
2. Bridge creates `WorkflowRunner(..., cancel_event=lease_lost)`.
3. `SweResearchLoop.run` result handling:
   - `status == "cancelled"` → `raise asyncio.CancelledError` (not a research
     error; the worker's lease-lost path expects this).
   - other non-`completed` status → `ResearchExecutionError`.
4. Handler cancellation sequence (engine already implements it):
   driver sees `cancel_event` → `machine.cancel(now)` → `cancel_invocation`
   effects → `cancel_invocations` cancels the Python asyncio tasks of open
   handlers (`runtime_dispatch.py`) → `CancelledError` inside
   `_execute_one_need` → re-raised, no failure evidence written; the run store
   records the terminal `cancelled` transition.
5. Fence context propagation: the driver task is created inside
   `execute_attempt_research`, so handler tasks created by
   `asyncio.create_task` inherit the same contextvars. `_raise_if_write_fenced`
   therefore still fires in handlers even before the engine's cancel reaches
   them. Keep the fence as the authoritative write guard; `cancel_event` only
   makes cancellation prompt.
6. Logging context: `run_research_loop` bound `wave_number` per wave
   (loop_control.py:134). The bridge replaces it: track the current wave in
   `_run_wave` and call `bind_log_context(wave_number=...)` inside
   `research.run_wave`/`research.execute_need`/`research.finish_wave`
   (`app/observability/context.py`). Do not drop the field.
7. SWE `limits.timeout_seconds` (1800 in the compiled definition) is a
   backstop only. The per-need deadline remains
   `settings.research_need_timeout_seconds`, applied in the bridge child
   handler exactly like `_run_need_executions` did. Do not move deadlines into
   the workflow definition.

### Known limitations to document, not fix here

- A handler that swallows `CancelledError` is not force-stopped
  (swe-runtime.md). The fence still blocks its writes; the driver reaps the
  task. Same limitation as the phase-2 machine everywhere else.
- SWE-level resume (`resume_run`) is **not** wired into the worker in this
  cutover. Worker recovery stays DB/lease-based (`docs/guides/research-durable-execution.md`
  §Recovery): attempt stays `researching`, the next claim re-executes from the
  persisted wave. The OverGraph run log is observability, not the recovery
  source of truth yet.

## 5. Run store in production

`WorkflowRunner(run_store=...)` persists run/invocation/events to
`OVERGRAPH_DIR/workflows/customer_<id>/research` (swe-overgraph.md).

Proposed wiring (parity-PR):
- `execute_attempt_research` already has `run` (execution.py:1163). Open one
  store per attempt: `WorkflowRunStore.open(catalog_root(settings.overgraph_dir),
  WorkflowHostContext(customer_id=str(run.customer_id), feature_id="research"))`,
  pass it as an extra `run_store` kwarg to the loop, close it in a `finally`
  after the loop returns.
- Use a unique run id per execution:
  `run_id=f"research-{attempt_id}-{uuid4().hex[:8]}"` with
  `input={"attempt_id": attempt_id}`. A stable run id would let a retry
  overwrite the previous attempt's events (`<run_id>:<seq>` keys are upserts).
- Ownership: the caller opens/closes the store; the bridge never closes it.

Open decision for the Lead — **default recommendation: defer the production
store to a follow-up PR**. Reasons:
- `immediate` WAL fsyncs every transition; the research loop has several
  transitions per wave. The measurement harness must show it is within the
  agreed wall-time budget before it is enabled in production.
- OverGraph 0.17 has no multiprocess writer lock. If research can run in a
  separate process while another process writes the same customer catalog, the
  store must be gated by a host lock first (or disabled).
- Recovery does not use the store yet, so enabling it in the cutover buys
  observability only.

If deferred, the cutover still wires `lease_lost`/cancel and leaves the store
API in place; a follow-up PR enables it after the measurement report and the
host-lock decision.

## 6. Wiring change in `execution.py`

Only the loop seam changes; keep kwargs shape stable:

```python
# execution.py:992-995 — body swaps from loop_control to the bridge
async def _run_research_loop(**kwargs: object) -> None:
    """Delegate to the SWE bridge. Imported lazily to avoid a cycle."""
    from app.services.research.swe_bridge import run_research_loop_via_swe

    await run_research_loop_via_swe(**kwargs)
```

- Call site `execution.py:1217` stays as is.
- Add `lease_lost=lease_lost` (and `run_store=` if §5 is enabled) to the kwargs
  block at execution.py:1217-1239. The bridge reads those keys and passes the
  rest through `wave_config_from_kwargs`.
- `start_wave` stays in the interface for one release: the bridge ignores it
  because `finish_research_wave` reads `attempt.research_wave` from the DB.
  Add an assertion/test that the two agree on resume, then drop `start_wave`
  from the kwargs in a follow-up.
- The parity-PR must not delete `loop_control.run_research_loop` yet; it stays
  present but unreachable during the parity step so a revert restores the old
  path with a one-line change.

## 7. Parity gates

Run from `backend/` unless stated. All must be green before the delete-PR.

Domain parity (the facit):
```bash
uv run pytest \
  tests/test_research_swe \
  tests/test_research_execution.py tests/test_research_loop.py \
  tests/test_research_loop_decision.py tests/test_research_assessment.py \
  tests/test_research_completeness.py tests/test_research_need_timeout.py \
  tests/test_research_eager_quality.py tests/test_research_worker.py \
  tests/test_research_progress.py tests/test_research_connection_release.py \
  -q
uv run pytest tests/research_reuse -m research_reuse -q
uv run pytest tests/test_swe_*.py -q
```
Deterministic measurement comparison (before/after the parity-PR, same machine):
```bash
uv run python scripts/benchmark_research_loop.py --runs 3 --json /tmp/cutover-{before,after}.json
```
Acceptance:
- identical domain fields per pair: `status`, `stop_reason`, `research_wave`,
  found/not_found/error counts, evidence set items, need-execution statuses,
  assessment/completeness passes, `reused_answer_id`/`provider_calls` on the
  warm run;
- wall time within the agreed budget (proposal: no worse than +10% median,
  no single run above +25%; Lead confirms after the task-4 report);
- no new LLM calls (`bind_usage_recorder` stays zero in fake mode).

Static/CI:
```bash
uv run ruff check app tests scripts/check_maintainability.py
uv run python scripts/check_maintainability.py
make test-swe            # cargo fmt/clippy/test + SWE pytest, builds swe_native
```
CI jobs that must be green: `backend`, `research-reuse`, `swe-runtime`
(`.github/workflows/ci.yml:111,116,147-176`) and the required **CI** check.
The `research-reuse` job is the external contract; it must stay green after the
delete-PR too.

Wiring test added in the parity-PR
(`backend/tests/test_research_swe/test_wiring.py`):
- monkeypatch `execution._run_research_loop` with a sentinel and assert
  `execute_attempt_research` calls it with `lease_lost` in kwargs;
- run the bridge with a pre-set `lease_lost` event and assert
  `CancelledError` propagates and the attempt is not marked `failed`;
- assert a cancelled run is persisted with status `cancelled` when a store is
  passed (keeps §4 and §5 honest).

## 8. Documentation updates (delete-PR or parity-PR, as marked)

| File | Change | Step |
| --- | --- | --- |
| `backend/AGENTS.md:50` | Drop “Research cutover is phase 5 — do not wire it here”; state that `execute_attempt_research` runs the wave loop on SWE via `research/swe_bridge.py`, link to this plan. | delete |
| `docs/specs/swe-inventory.md:40-61` | “Move into SWE later” → “Moved into SWE” with the actual bridge targets; “Remove after verified cutover” → what was deleted (with this doc's §2). | delete |
| `docs/specs/swe-swd-1.0.md` follow-up list | Mark phase 5 done; short description + link to this doc. | delete |
| `docs/specs/swe-runtime.md` | New “Research wave loop” subsection: node graph (`run_wave → map → finish_wave → decision`), handler names, cancel/lease semantics, deadline split (workflow backstop vs per-need timeout). | parity |
| `docs/specs/swe-overgraph.md` | Production wiring section if §5 is enabled (catalog root, customer context, run id, who opens/closes); otherwise a “not wired to production yet” note. | parity |
| `docs/specs/swe-provider.md` | Remove “Not in this phase: research bridge/cutover”; add that the research loop still calls Jev inside assessors, not through `decision(provider)` yet. | parity |
| `docs/guides/research-durable-execution.md:52,98` | Worker section: the loop runs on SWE; recovery section: DB/lease recovery is unchanged, run store is observability. | delete |
| `docs/guides/research-baseline-measurement.md` | Note that after cutover the harness measures the SWE loop through the same entry point. | parity |
| `docs/specs/swe-cutover.md` | This document; add a final “executed” status block with PR links after the delete-PR. | delete |

## 9. Two-step ordering and rollback

**Preconditions:** task-4 measurement report exists and names the winning
workflow; Lead has confirmed the cutover (Q4: measurement is the gate);
#408/#409 merged; `swe_native` build job green.

**Step 1 — parity PR** (done; [#412](https://github.com/kajmund/socialism/pull/412), branch `feat/swe-research-cutover`):
1. mechanical seam renames (§3) + test import fix;
2. bridge changes: public imports, `lease_lost` → `cancel_event`, cancelled →
   `CancelledError`, wave-number log context, optional `run_store`, unique run
   id, `start_wave` assertion;
3. `execution.py` wiring (§6) + `test_wiring.py`;
4. `swe-runtime.md`, `swe-provider.md`, `research-baseline-measurement.md`
   updates.
Keep `loop_control.run_research_loop` present but unreachable.

**Step 2 — delete PR** (done; [#414](https://github.com/kajmund/socialism/pull/414)):
1. delete `loop_control.run_research_loop` (§2.2) and unused imports;
2. delete `execution._run_need_executions` (§2.1);
3. delete `tests/test_research_swe/test_parity.py` (its baseline no longer
   exists); keep `test_wiring.py` and the full research suites as regression;
4. docs updates marked “delete” in §8; mark this doc executed;
5. run all gates from §7; confirm the benchmark comparison recorded in step 1
   still holds.

**Rollback ladder**
- Before step 1 merges: close the PR; nothing changed.
- Step 1 merged, step 2 not: revert step 1's wiring commit → the old
  `loop_control.run_research_loop` is still present and reachable through the
  original seam body; no data migration needed (research DB schema untouched;
  OverGraph workflow catalogs are additive and can be ignored or deleted).
- Step 2 merged, regression found: revert step 2 (restores the old loop code,
  still unreachable), then revert step 1 if the old path must be live again.
  Never introduce an “if SWE fails, run the old loop” fallback.

## 10. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Behaviour drift between bridge and old loop | Evidence/assessment/stop-reason differences | Differential suite (§7) plus all `test_research_*` and `research_reuse` before/after; benchmark domain-field comparison. |
| Cancellation race: lease lost while a handler writes | Post-lease writes, duplicate evidence | Fence stays authoritative in every handler write path; add cancel test; keep `_execute_one_need` CancelledError path untouched. |
| Lost `wave_number` log context | Harder incident debugging | Bridge binds it per handler (§4.6); assert in a test or log smoke. |
| Per-transition `immediate` WAL overhead | Slower research attempts | Run-store decision (§5); measure with the harness; defer if outside budget. |
| OverGraph multiprocess writer | Corrupted/undefined catalog behaviour | Single-writer process assumption; host lock or defer store before enabling. |
| SWE event materialization O(events) per transition | Slower long runs | Loop has few transitions per attempt; measure; Rust event cursor is a later optimisation (swe-runtime.md). |
| Private imports keep drifting while parity PR is open | Merge conflicts | Land the mechanical renames first in their own commit; bridge imports only public names before wiring. |
| `start_wave` vs DB `research_wave` mismatch on resume | Wrong assessment pass/wave | Assert equality on resume in the bridge or a test; drop `start_wave` in a follow-up. |
| Scope creep into Jev/provider decisions | Unreviewable PR | §11 do-not-touch list; provider decisions are not used by the research loop in this cutover. |

## 11. Do not change in this cutover

- `loop_decision.py` decision policy, stop reasons, assessment/completeness
  semantics, quality artifacts, Jev/relevance calls.
- Question reuse, graph reuse, `QuestionEvidenceGraph`, mem0, knowledge graph,
  OverGraph knowledge catalogs.
- `ResearchRouter`, provider registry, prompt catalog, prompt text.
- Research DB schema, attempt/evidence-set statuses, progress events, answer
  review/TTL, freeze behavior.
- `research_worker` claim/lease/heartbeat protocol and the API surface.
- `execute_attempt_research` prelude, exception mapping, fail-closed rules.
- `execute_research_question_dag` / `question_attempt_worker` orchestration
  (separate future SWE consumer, listed in swe-inventory.md).
- Jev cache L1/L2 for SWE providers: it exists but the research loop does not
  route assessment/planning through `decision(provider)` yet. Do not migrate
  LLM calls to providers in this cutover.

## 12. Open questions for the Lead

1. **Run store in production (§5):** enable now or defer? Recommendation:
   defer until the measurement report and the single-writer/host-lock decision.
2. **Wall-time budget:** confirm the §7 threshold (+10% median / +25% single
   run, fake mode) or replace it with the task-4 report's Pareto criterion.
3. **BRIDGE seam name:** keep `execution._run_research_loop` as the patchable
   seam (recommended; least churn) or rename it `run_research_loop` (public)
   in the parity-PR?
4. **`start_wave`:** drop from the kwargs in the delete-PR or keep one release?
   (Recommendation: keep one release with an equality assertion.)
5. **`loop_control.py` rename to `wave.py`:** defer as a separate cleanup PR
   (recommended) or include in the delete-PR?
