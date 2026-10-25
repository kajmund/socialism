# Owner read/write contention: profiling report

Status: measurement only. No production scheduling change is enabled by default.
The owner keeps the inline read path; the profiling flags are opt-in.

## Correcting the 127.5 ms figure

The earlier "mutation p95 127.5 ms" was produced with 20 mutation samples and a
percentile helper that selected `floor(0.95*n)` – for n=20 that is the **maximum
sample**, not a stable p95. The same benchmark rerun produced a 297 ms maximum.
It is a tail outlier, not a reproducible p95.

The profiler now uses nearest-rank percentiles, reports p50/p95/p99/max/n, and
runs 100 mutations per phase. With the same 8-reader load the stable mutation
p95 is about **18.7 ms**, not 127 ms. The original observation was directionally
useful (there is contention), but the number was a max mislabelled as p95.

## Method

`backend/scripts/profile_owner_read_write.py` starts a real owner process with
`--no-sync --profile-lag`, seeds 2 000 facts, and measures separately:

- no reads (baseline mutations),
- reads only (1/8/16 concurrent bounded retrieval loops),
- reads + writes (same readers, then 100 mutations),
- query bounds 20 and 200 at 8 readers.

Instrumentation:

| Source | What it measures |
| --- | --- |
| client mutation wall | end-to-end mutation latency including socket/event-loop wait |
| owner `queue_wait_seconds` | time from request parse/enqueue to worker dequeue |
| owner `commit_seconds` | commit call inside the worker thread |
| owner `read_seconds` | time inside `handle_read` (query execution + hydration) |
| owner `event_loop_lag_seconds` | 5 ms monitor drift in the owner event loop |
| health ping | client-observed event-loop responsiveness (health uses the loop) |
| owner read bytes/ops | transport volume per bounded query |

## Results (inline owner, 100 mutations)

| Phase | Mutation p50/p95 | Mutation queue p95 | Commit p95 | Read client p95 | Read exec p95 | Loop lag p95 | Health p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No reads | 0.7 / 1.6 ms | 0.08 ms | 0.9 ms | — | — | 6.9 ms | 4.6 ms |
| 1 reader + writes | 1.6 / 7.9 ms | 0.08 ms | 0.9 ms | 9.6 ms | 0.8 ms | 6.9 ms | 4.6 ms |
| 8 readers, read-only | — | — | — | 19.7 ms | 0.8 ms | 10.6 ms | 19.6 ms |
| 8 readers + writes | 6.6 / **18.7 ms** | 3.0 ms | 2.9 ms | 19.1 ms | 0.8 ms | 10.6 ms | 19.6 ms |
| 16 readers + writes | 11.4 / **26.9 ms** | 6.4 ms | 2.7 ms | 28.3 ms | 0.8 ms | 14.8 ms | 25.1 ms |

### Where the write delay sits

At 8 readers the mutation p95 is 18.7 ms. Instrumented queue wait (3.0 ms) and
commit (2.9 ms) account for only ~6 ms. The residual ~13 ms is before queue
entry: owner event-loop occupancy (loop lag p95 10.6 ms), socket delivery and
response scheduling. Queue wait is not the main cause.

### Where read latency sits

Bounded query execution is **0.8 ms p95**, while client read latency is
**19.7 ms p95** at 8 readers. The read client also spends most of its time
waiting on the owner event loop/socket, not executing the query.

Large results make this much worse:

| Bound at 8 readers | Client p95 | Owner exec p95 | Avg owner bytes/read |
| --- | ---: | ---: | ---: |
| 20 | 18.1 ms | 0.8 ms | 3.8 KB |
| 200 | 257 ms | 3.3 ms | 37 KB |

The 200-bound tail is dominated by event-loop/response work, not the vector
query itself. This is a direct argument for keeping result pages small and
bounded rather than transporting larger candidate sets.

### Reads vs writes interaction

Read p95 is essentially unchanged with writes running (19.7 ms read-only vs
19.1 ms read+write at 8 readers). The asymmetry is the other way: writes suffer
because reads occupy the single event loop. At this load, writes do not make
reads slower, but reads make write tails longer.

### Separate scheduling experiment (opt-in, not default)

`--read-offload` runs `handle_read` in a thread. At 8 readers it reduced
mutation p95 from 18.7 ms to **11.5 ms**, but increased read p95 from 19.1 ms to
**29.4 ms** and owner read execution p95 from 0.8 ms to 24.2 ms (thread/lock
contention). It is a real tradeoff, not a free win; it is not enabled by default
and no atomicity/ordering behavior was changed.

## Conclusions

1. The 127.5 ms claim was a max-like outlier from the old percentile; stable
   contention is ~19 ms mutation p95 at 8 readers, with a long tail.
2. The largest measured lever is **response size**: 37 KB/read at bound 200
   produced a 257 ms read tail although query execution stayed at 3 ms.
3. Mutation delay is dominated by pre-queue/event-loop scheduling, not queue
   wait or commit.
4. Offloading reads trades write tail for read tail; do not adopt without a
   product decision and more safety tests.
5. No research, SSR or SWE behavior was changed. The profiling flags are
   opt-in; default owner behavior and retrieval parity are unchanged.

## Remaining profiling questions

- Tie each read request to a server-side pre-parse timestamp to split socket
  wait from event-loop delay exactly (current residual combines them).
- Test response streaming/compression or a hard byte cap instead of larger JSON
  responses.
- Repeat on CI hardware and with sync-on-commit enabled; this run used `--no-sync`
  to isolate scheduling.
