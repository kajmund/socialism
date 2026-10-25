# Owner read/write scheduling: 3072-dim profiling and bounded read executor

Status: bounded read executor is implemented (default 4 workers) and verified.
No `Catalog` lock change was made in this slice.

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

## 4. Verification

- `backend/scripts/verify_owner_multiprocess_fastapi.py` passed end-to-end with
  the read executor enabled: two real backends, owner restart, concurrent
  ingest/retrieval/answer reuse, **0 local knowledge-catalog writes/opens**, and
  the owner-authored scope marker still drives graph reuse.
- `backend/tests/test_owner_profiling.py` covers bounded workers, event-loop
  lag, and close waiting for an in-flight read before closing the catalog.
- Full suite and CI are re-run after the change; owner atomicity, idempotency,
  receipts and retrieval parity are unchanged.

## 5. Correction of the earlier 127.5 ms figure

The old 20-sample helper selected the maximum value as “p95”. With 1 000
samples and 3 072 dimensions the reproducible inline mutation p95 is **137 ms**;
the old 127.5 ms was directionally right but mislabelled. The new profiler fixes
the percentile calculation.

## 6. Next steps (not done here)

1. **Separate lock-narrowing change** in `Catalog`: audit `RLock` scope, close/read
   race, snapshots, flush and restart; then rerun this exact benchmark. No lock
   change is included in this slice.
2. **Independent review before considering lock changes safe** (per the plan).
3. Tantivy after the owner scheduling work.
4. Micro-batched durable sync remains a separate throughput optimization.
