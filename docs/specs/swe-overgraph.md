# SWE phase 3 — OverGraph run store

**Status:** Implemented. Phase-3 persistence for the in-memory SWE machine.
**Not in this phase:** Jev provider/cache (phase 4), research cutover (phase 5), expert/routing adapters (phase 6).

## Scope

`run_workflow` and `WorkflowRunner` execute the SWD 1.0 machine in memory. This
phase makes a run durable without changing engine semantics:

- one OverGraph catalog per customer and top-level feature;
- every transition is one write transaction;
- an append-only event log per run;
- a persisted run can be resumed after a process crash.

The engine (`app/swe/`) never imports OverGraph. `app/swe/run_store.py` owns the
contract (`RunRecord`, `InvocationRecord`, `RunStore`);
`app/services/overgraph/workflows.py` implements it.

## Catalog layout and isolation

```
OVERGRAPH_DIR/
  workflows/
    customer_<customer_id>/
      <feature_id>/          # research | expert_routing | model_routing | group_chat | webcrawler
```

- The directory comes from `app.swe.features.workflow_catalog_dir` and is derived
  from trusted host context only. Customer and feature never come from YAML.
- The catalog opens with `create_if_missing=True`, `dense_vector_dimension=1`
  (no vectors are stored) and **`wal_sync_mode="immediate"`**: `commit` fsyncs
  the WAL before the driver continues. A committed transition survives a host
  crash that loses the page cache.
- One process owns a catalog; calls are serialized by an `RLock` like
  `app/services/overgraph/catalogs.py`. `WorkflowRunStore.open` is the only
  opening path in this phase.
- A unit test asserts that two customers and two features get three different
  directories and that a run written in one is absent in the others.

## Node model

All nodes carry the type label plus a scope label
`workflow.customer.<customer_id>.<feature_id>`.

### `WorkflowRun`

Key = `run_id`. Properties:

| Property | Meaning |
| --- | --- |
| `run_id` | Same as the key |
| `definition_sha256` | Frozen compiled definition; a resume with another definition is rejected |
| `status` | `running`, `completed`, `incomplete`, `failed`, `cancelled` |
| `input_json` | Canonical JSON of the run input |
| `output_json` | Canonical JSON of the root scope locals at the last persisted transition (`""` when `null`) |
| `error_json` | `{kind, message, path}` (`""` when `null`) |
| `started_at_ms` | Driver clock at `Machine.start` (monotonic ms) |
| `updated_at_ms` | Driver clock at the last persisted transition |
| `finished_at_ms` | Set on the first terminal transition, `0` while running |
| `last_seq` | Highest persisted event sequence for the run |

### `WorkflowInvocation`

Key = `invocation_id` (`<run_id>:<node_id>:<branch_path>:<loop_epoch>:<serial>`,
the id the machine emits in `invoke_handler`). Properties: `run_id`, `node_id`,
`ok` (`1`/`0`), `value_json` (`""` for failures), `error` (`""` for successes),
`completed_at_ms`.

### `WorkflowRunEvent`

Key = `<run_id>:<seq>`. Properties: `run_id`, `seq`, `type`, `node_instance_id`,
`node_id`, `result_ref`, `lineage_json`, `payload_json`. Sequence numbers come
from the machine and start at 1; the store appends, never rewrites or renumbers.

## Atomic transitions

Each persisted transition is a single `begin_write_txn()` that upserts:

1. the `WorkflowRun` snapshot,
2. every event the machine emitted since the previous snapshot,
3. the `WorkflowInvocation` for a handler completion or failure (when present),
4. then `commit`.

A failure anywhere in the transaction rolls back, so an interrupted write leaves
the previous transition intact — never a run with an event it does not have, or
an invocation result without its event. A regression test commits a deliberately
invalid node in the middle of a transaction and asserts that neither node exists
afterwards.

`immediate` WAL is the durability boundary. The store does not call `sync()`
per transition; `sync()` exists for callers that need a full flush before
reading through another runtime.

## Resume

`resume_run(compiled, handlers, *, run_store, run_id, ...)` and
`WorkflowRunner(...).resume(run_id)`:

1. Load the `WorkflowRun`. Missing run → typed `resume` error. Different
   `definition_sha256` → typed `resume` error.
2. Terminal status → return the persisted status, output, error and events
   without creating a machine or calling any handler.
3. Running status → start a fresh `Machine` with the persisted `run_id`, input
   and `started_at_ms`, then re-drive it. The machine is deterministic, so the
   same nodes schedule in the same order with the same `invocation_id`s.
4. For every `invoke_handler` effect whose `invocation_id` already has a
   `WorkflowInvocation` node, complete (or fail) the invocation from the graph.
   Only the remaining effects spawn Python handlers.
5. The run continues to a terminal status and the final snapshot is persisted.

The `started_at_ms` replay means the deadline is the original
`started_at_ms + limits.timeout_seconds`, not a fresh window. A run that
exhausted its timeout while the process was down fails on the first transition
after resume. Monotonic milliseconds (`WorkflowClock`) are system-wide on one
host, which makes this meaningful across processes on the same host; the value is
not wall-clock and must not be rendered as a timestamp.

### Guarantees

- Committed transitions are durable and atomic.
- A persisted invocation result is replayed, not recomputed.
- Event order and sequence are identical to an uninterrupted run; replaying a
  transition is idempotent (same node keys, same properties).
- A terminal run resumes as a pure read.

### Non-guarantees

- **Handler side effects are at-least-once.** A handler whose result was not
  committed before the crash runs again on resume. Exactly-once side effects
  require idempotent handlers. This is deliberate: the store never claims a
  handler did not run.
- No exactly-once for external calls made by handlers; the store does not
  deduplicate them.
- No multi-process writer coordination. OverGraph 0.17.0 does not provide an
  exclusive multiprocess writer lock; a host lock is a follow-up.
- No cross-transaction snapshot over several runs, no run-list query API, no
  retention/pruning policy yet.
- Event materialization is O(events) per transition: `Machine.events()` returns
  the whole in-memory sink. This is the phase-2 engine contract and is accepted
  here; a dedicated event cursor in the Rust sink is a later optimisation.

## API

```python
store = WorkflowRunStore.open(root, WorkflowHostContext(customer_id="1", feature_id="research"))
result = await WorkflowRunner(compiled, handlers, run_store=store).run(input, run_id="run-1")
result = await resume_run(compiled, handlers, run_store=store, run_id="run-1")
stored = await store.load_run("run-1")
events = await store.events("run-1")
invocations = await store.replay_results("run-1")
store.close()
```

`run_workflow` keeps the phase-2 signature and is an unpersisted runner, so
`run_store=None` costs no extra work. `run_store` lives on `WorkflowRunner`
because `PLR0913` caps `run_workflow` at seven arguments and the repository
forbids new `noqa` exemptions.

## Tests

`backend/tests/test_swe_persistence.py` (`swe_runtime` marker, skipped when
`swe_native` is not built):

- run/event/invocation persistence and exact event parity with the machine result;
- failed handler → failed invocation record and persisted run error;
- re-recording a transition is idempotent (no duplicate events);
- failed transaction writes no node at all;
- crash mid-run → resume replays the persisted invocation, re-runs only the
  unfinalised handler, and produces the same output and event sequence as an
  uninterrupted run;
- terminal run resumes without calling handlers;
- definition mismatch is rejected;
- per-customer/per-feature isolation;
- timeout fails and persists the run;
- resume keeps the persisted start time, so the original deadline applies.

## Production wiring

The run store is implemented and tested, but it is **not production-wired** in
the research cutover. No per-attempt `WorkflowRunner(run_store=...)` is created
in production: `immediate` WAL costs one fsync per transition, OverGraph 0.17
has no multiprocess writer lock, and research recovery is still the DB/lease
path. The store is used by tests and the measurement harness; enabling it is a
follow-up after the host-lock and cost decisions.

## Follow-ups

- Phase 4: the Jev cache gets its own catalog in the same per-customer layout.
- Host lock (or single-owner enforcement) before claiming crash safety across
  processes.
- Event cursor in the Rust sink when fan-out grows.
- Retention/compaction policy for finished runs.
