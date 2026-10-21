# Research loop baseline measurement

The baseline harness measures the **current** research loop
(`execute_attempt_research`) so the SWE experiment (task-4) has something to
compare against. It is deliberately deterministic and offline.

`backend/scripts/benchmark_research_loop.py`

After the research cutover the same entry point (`execute_attempt_research`)
runs the SWE bridge wave loop; the harness therefore measures the cutover path
without changing its interface. Domain fields are expected to be identical.
The **first cold pair in a fresh process** also pays one-time SWE
initialization (~0.1-0.2 s: lazy bridge imports, runtime import and first
definition compile). Use a discarded warmup or more `--runs` when timing the
cutover, and keep the raw JSON from both sides.

## Cutover gate (before/after, 2026-10-22)

Measured from a clean `origin/main` worktree (before) against the cutover
worktree (after), alternating runs with a discarded warmup on each side:

| Measurement | Cold median ratio | Paired p95 | Domain fields |
| --- | --- | --- | --- |
| Steady state (discarded warmup in the same process) | **0.9962** | **1.1671** | identical |
| Literal fresh process per invocation | 1.2968 | 1.7056 | identical |

The fresh-process row fails only because every new process pays the one-time
SWE initialization above on its first research attempt; pairs two and three sit
at the baseline level. Production research runs inside a long-lived worker, so
the steady-state row is the certification, and the thresholds are unchanged.
The raw JSON from both sides (`cutover-{before,after}-clean-*.json`) is kept
locally; rerun both sides in a quiet window if the numbers are contested.

## Command

```bash
cd backend
uv run python scripts/benchmark_research_loop.py --runs 3
uv run python scripts/benchmark_research_loop.py --runs 3 --json /tmp/research-baseline.json
```

`--runs N` measures N independent cold/warm pairs. Each pair gets its own
temporary working directory, SQLite database and OverGraph catalog, so a pair
never reuses another pair's knowledge. `--data-dir` keeps the working directory
instead of a temp directory. Raw JSON is written only where `--json` points; do
not commit it.

## What a pair does

Every pair uses one question:

1. **cold** attempt: research objective + deterministic fake planner child need,
   fake research source, fake embeddings, programmatic assessor/completeness
   (no LLM). The attempt retrieves evidence, assesses it and freezes. Freezing
   publishes the answer episode into OverGraph.
2. **warm** attempt: the same question in a new run/attempt. The production
   `research.result.reused` path matches the saved answer by canonical question
   identity and binds the frozen evidence set without any source work.

The fake planner child need makes the cold run exercise the wave/fan-out shape
(two needs, one provider retrieval, one synthesized main answer). The warm run
resolves through exact saved-answer reuse (one need, zero provider calls).

The harness passes `research_objective` (not an explicit `ResearchPlan`) on
purpose: `reuse_completed_result` only runs on the main-first start path. An
explicit plan snapshot would persist on the attempt and skip saved-answer reuse.
SQLite is file-backed (WAL) rather than in-memory because need workers open
their own sessions; this matches the research test fixtures.

The harness binds `app.llm.bind_usage_recorder` around every run, so the
`llm_calls` metric is a real count of LLM client calls, not an assumption.

## Metrics

| Metric | Meaning |
| ------ | ------- |
| `wall_ms` | `execute_attempt_research` wall time per attempt (setup excluded) |
| `median_wall_ms`, `p95_wall_ms` | distribution over the N pairs |
| `needs` | runtime needs for the attempt |
| `need_durations_ms` | per-need `research_need_executions` start→complete durations |
| `found` / `not_found` / `error` | frozen EvidenceSet item statuses |
| `providers` | evidence items grouped by provider |
| `provider_calls` | calls actually made to the fake research source |
| `reused_answer_id` | `answer_fact_id` from the persisted `research.result.reused` reference |
| `reuse_match` | match kind (`exact` for a canonical saved answer) |
| `llm_calls` | recorded LLM client calls (must be 0 in fake mode) |
| `stop_reason` | `attempt.research_stop_reason` |

## Baseline (example run, local machine)

`--runs 3`, 2026-10-21, Apple silicon macOS:

```text
cold median_ms≈170–190 p95_ms≈175–195 provider_calls=3 llm_calls=0
warm median_ms≈10–15   p95_ms≈12–15   provider_calls=0 reused_answers=3 llm_calls=0
cold_to_warm_median_speedup≈10–18x
```

Treat the absolute times as machine-dependent. The stable signals are:

* cold runs call the provider; warm runs do not,
* warm attempts carry a `reused_answer_id` with `reuse_match=exact`,
* `llm_calls` stays 0, proving the fake mode touches no model,
* cold attempts run two needs, warm attempts one.

This measures **orchestration and knowledge reuse**, not research quality. A
fake source cannot tell whether the research answer is any good.

## Interpretation rules

* Report fake mode explicitly; never present these numbers as research quality.
* Compare medians and p95 on the same machine and the same `--runs` count.
* A warm run is only "reuse" when `reused_answer_id` is set and
  `provider_calls == 0`. Evidence still shows the original provider label
  because a saved answer replays its frozen basis.
* Do not add live/LLM providers here. The SWE experiment (task-4) owns any live
  mode and its cost accounting.

## Limitations

* Only the exact saved-answer reuse path is exercised; graph-candidate reuse
  (`lookup_graph_evidence`) is not seeded in this fixture.
* SQLite with WAL and one process; not a production concurrency measurement.
* The plan shape is fixed by the fake planner child need. Extend the harness
  deliberately if a metric needs a different shape, and keep the fake mode
  labelled.
