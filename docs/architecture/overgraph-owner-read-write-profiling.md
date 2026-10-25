# Owner read/write scheduling: 3072-dim profiling and bounded read executor

Status: bounded read executor (**default 4 workers**) and the readers-share/
writer-exclusive Catalog lock (**default for the owner**) are implemented and
verified. `--lock-mode global` remains the diagnostic and safe fallback.

## 1. Realistic benchmark

`backend/scripts/profile_owner_read_write.py` now runs 3 072-dimensional
vectors, 1 000 seeded facts and **1 000 mutations per phase**, with nearest-rank
p50/p95/p99/max (not the old `floor(0.95*n)` helper). It records:

- client mutation wall, owner queue wait, commit, read execution,
- a 5 ms event-loop-lag monitor inside the owner,
- client health latency (health is served by the same event loop),
- owner read bytes/ops and bounded query sizes 20/200.

## 2. What changed in the owner

- Reads run on a **bounded read executor** (`ThreadPoolExecutor`, default 4
  workers; `--read-workers N`; `0` keeps them inline for experiments).
- The writer has its own **single-threaded executor**, separate from reads.
- Close waits for `_reads_inflight == 0` before shutting the read executor and
  closing the catalog, so a catalog cannot be closed under an active read.
- Inline mode remains available for comparison; the default is the bounded
  executor (`--read-workers 4`).
- The owner default is now `read_write`; `--lock-mode global` keeps the old
  global RLock as a diagnostic fallback.
- Tests cover the executor path, close/read race, lag monitor and the existing
  owner contracts.

## 3. Results (1 000 mutations, 8 readers)

| Owner mode | Mutation p50/p95 | Mutation p99/max | Queue p95 | Commit p95 | Loop lag p95 | Read client p95 | Read exec p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Inline (baseline before) | 103 / **137 ms** | 159 / 190 ms | 50 ms | 1.6 ms | **80 ms** | 151 ms | 15 ms |
| Read executor, 4 workers | 50 / **79 ms** | 93 / 103 ms | 1.2 ms | 11.8 ms | **1.5 ms** | 163 ms | 66 ms |
| Read executor, 8 workers | 27 / **71 ms** | 90 / 104 ms | 1.2 ms | 12.3 ms | **1.5 ms** | 150 ms | 123 ms |

No-read baseline mutation p95 is 1.8 ms.

Findings:

- Moving reads off the event loop cuts event-loop lag from **80 ms to 1.5 ms**
  and mutation p95 from **137 ms to 79 ms** — a ~42 % reduction, verified on
  1 000 samples and 3 072-dimensional vectors.
- It does **not** reach the earlier optimistic 24 ms in this slice. The remaining
  write delay is no longer event-loop scheduling: queue wait is ~1 ms, while
  read execution p95 rises to 66 ms (4 workers) / 123 ms (8 workers) and commit
  p95 rises to ~12 ms. That points at `Catalog` lock contention, which is a
  separate change (step 4) and was deliberately **not** touched here.
- Reads get slower with the read executor (client p95 ~150–163 ms vs 151 ms
  inline; execution 15 → 66/123 ms) because reader threads contend on the
  catalog lock. This is the next tradeoff to solve with lock narrowing.
- More read workers are not monotonically better: 8 workers slightly improved
  mutation p95 but made read execution p95 much worse (123 ms). Four is the
  current bounded default.

### Bounded result size at 8 readers

| Bound | Inline client p95 | Inline exec p95 | 4-worker client p95 | 4-worker exec p95 | Bytes/read |
| --- | ---: | ---: | ---: | ---: | ---: |
| 20 | 138 ms | 15 ms | 161 ms | 66 ms | ~4 KB |
| 200 | 232 ms | 25 ms | 337 ms | 117 ms | ~37 KB |

Large result pages still dominate the client tail, independent of scheduling.

## 4. Lock A/B experiment (now default)

Lock wait instrumentation (`TimedRLock`) and the readers-share/writer-exclusive
`ReadWriteLock` were added for the isolated experiment. After the measurements
below and an independent review, the owner default is `read_write` with four
read-workers; `--lock-mode global` remains available as a diagnostic and safe
fallback. `Catalog` itself still defaults to the global lock for direct callers.

| Mode (8 readers, 1 000 mutations) | Mutation p50/p95/p99 | Read client p95 | Read exec p95 | Event lag p95 | Writer lock wait p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Inline, global | 105 / 135 / 163 ms | 149 ms | 14.9 ms | 80 ms | 10.1 ms |
| 4 read workers, global | 51 / 81 / 90 ms | 160 ms | 64.5 ms | 1.5 ms | 12.5 ms |
| 4 read workers, read/write lock | 28 / **39 / 45 ms** | **56.5 ms** | **16.1 ms** | 5.6 ms | 11.5 ms |
| 8 read workers, read/write lock | 21 / **35 / 41 ms** | 51.2 ms | 22.7 ms | 7.5 ms | 11.0 ms |

- The read/write lock cuts mutation p95 from 81 to 39 ms with 4 workers and
  reduces read execution from 64.5 to 16.1 ms. This is consistent with
  read-read serialization being a real contributor.
- The target ~24 ms is **not** reproduced. Remaining time is spread across
  writer lock wait (~11 ms p95), commit, read execution, socket/JSON and the
  remaining GIL/engine work; it is not one single lock wait.
- The raw OverGraph probe (`scripts/probe_overgraph_concurrency.py`) at 3 072
  dimensions ran 8 concurrent readers and a concurrent writer with no errors
  (parallel read p50 ~3.1 ms), which supports the premise that concurrent
  published reads are usable. This is a probe, not a proof of every API path.
- Native `begin_write_txn()` still releases the Catalog guard after opening the
  transaction; the experiment does not claim transaction-wide reader exclusion.
  That must be resolved before any lock-mode default change.
- Independent review found: non-reentrant
  reader/writer locks (fixed with owner-aware reentrancy and an explicit error
  for writer acquisition inside a read callback), an unguarded mode switch
  (fixed by switching under the old lock), a read-executor barrier that counted
  awaiting rather than executing tasks (fixed by completing in the worker
  thread and rejecting reads after close), and a health-report race (fixed with
  snapshots under the metrics lock). New tests cover nested reads, read-inside-
  write failure, close/read, mode switch and post-close reads.
- Remaining latent limitation: native `begin_write_txn()` releases the guard
  before transaction work. This existed under the global lock too; the owner is
  protected by executor ordering plus the transaction barrier tests, and direct
  maintenance writes are unreachable in owner mode. Native conflict retry is
  fixed so a closed transaction cannot mask a conflict.

## 5. Durable-sync mixed workload

Same four modes with `--sync` enabled (the production durable-ack path):

| Mode (8 readers, 1 000 mutations + sync) | Mutation p50/p95/p99 |
| --- | ---: |
| Inline, global | 131 / 188 / 208 ms |
| 4 read workers, global | 63 / 95 / 114 ms |
| 4 read workers, read/write lock | 45 / **54 / 61 ms** |
| 8 read workers, read/write lock | 40 / **51 / 59 ms** |

Durable sync shifts all modes up by roughly 15–45 ms, but the ordering and the
read/write-lock advantage remain. Eight workers are only marginally better than
four while adding event-loop and read-execution cost; four stays the default
candidate.

## 6. Transaction lifecycle verification

The owner already has the right serialization point: `_run_worker` submits the
entire synchronous `_apply` operation to one writer executor. For `batch`,
`conditional` and `embedding` mutations, `begin_write_txn → precondition reads
→ node/edge writes → receipt → commit/rollback` runs inside that one thread with
no `await`. Receipts are inside the same transaction.

`tests/test_owner_transaction_isolation.py` adds a deterministic test seam that
pauses the writer after staging nodes and before commit:

- Reader during an open transaction sees exactly the previous committed state,
  never a partial node set (verified under both global and read/write lock).
- Releasing the barrier exposes the complete committed set.
- A failing edge after staging rolls back; no partial rows and the next
  mutation still works (no stuck transaction).
- Conditional conflict leaves visible state unchanged.
- Owner shutdown waits for the open transaction; reopening the catalog shows
  either no new rows or the complete new set, never a partial set.

Fact/answer/clause writes perform their read-modify-write preparation before
submitting a batch, but the submitted batch carries `expected_*`/preconditions
and is retried on conflict; the mutation itself, provenance and receipt commit
atomically. All owner-migrated mutation paths use this protocol. Direct writers
outside the Owner (document QA, legal claims, mem0, SWE run store) still exist;
they are not covered by the owner lock-mode experiment and `write_paths_ready`
remains false.

## 7. Ingest A/B

Controlled two-backend harness runs with the same data:

| Owner read workers | End-to-end ingest | Dispatch |
| --- | ---: | ---: |
| 0 (inline) | 0.456 s | 0.198 s |
| 4 (bounded executor) | 0.474 s | 0.210 s |

The earlier 1.09 s ingest was not reproducible in this A/B; the executor is not
shown to regress ingest. The controlled difference is ~4 %.

## 8. Lifecycle hardening and dependency

- Read-executor completion is now an idempotent per-read token. A failed
  submission, cancellation or worker completion finishes exactly once; a
  fault-injection test asserts `_inflight` returns to zero and `owner.close()`
  completes.
- Overgraph was upgraded separately from 0.17.0 to **0.17.1** (lockfile
  regenerated with `uv`). The published owner transaction/read tests and the
  multiprocess harness pass against the new wheel.
- Remaining latent review findings are documented (typed closed-catalog error,
  maintenance while a native transaction is open).

## 9. Verification

- `backend/scripts/verify_owner_multiprocess_fastapi.py` passed end-to-end with
  the read executor enabled: two real backends, owner restart, concurrent
  ingest/retrieval/answer reuse, **0 local knowledge-catalog writes/opens**, and
  the owner-authored scope marker still drives graph reuse.
- `backend/tests/test_owner_profiling.py` covers bounded workers, event-loop
  lag, and close waiting for an in-flight read before closing the catalog.
- Full suite and CI are re-run after the change; owner atomicity, idempotency,
  receipts and retrieval parity are unchanged.

## 10. Correction of the earlier 127.5 ms figure

The old 20-sample helper selected the maximum value as “p95”. With 1 000
samples and 3 072 dimensions the reproducible inline mutation p95 is **137 ms**;
the old 127.5 ms was directionally right but mislabelled. The new profiler fixes
the percentile calculation.

## 11. Next steps (not done here)

1. Keep `--lock-mode global` as fallback during rollout and monitor close/
   snapshot/flush/restart in production.
2. Address the remaining latent findings from the independent review (typed
   closed-catalog error, maintenance while a native transaction is open,
   read-executor submission-failure leak).
3. Tantivy after the owner scheduling work.
4. Micro-batched durable sync remains a separate throughput optimization.
