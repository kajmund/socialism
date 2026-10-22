# Research SWE experiment v2 — live measurement (v5)

**Observational instrumentation harness.** The v1 artifact
(`benchmark_research_swe.py`, frozen sha `a00ba565…`, n=8) remains the cutover
basis; v2 does not replace its gates. This document records the completed live
measurement and the history of the measurement-infrastructure fixes that led to
it.

## Metadata

- **Main live artifact**: `data/research_swe/v2-c39af043803c-20261022T100637Z`
  - git HEAD: `fd70820194858dfead55c7c3983a30adf683b1ac`
  - v2 harness sha256: `c39af043803c707c510ccf7eefcc5b2890ca594b3fc6e36c6f1069987ae6fe1c`
  - test sha256: `f8cc8895f3b129d6c7c8e98d61d882de66789f84e0eaff8cbbf4ddcd32df0782`
  - samples: 12 (2 questions × 3 arms × 2 repeats), **11 `ready` + 1 `failed`**
  - fixture: `source_1`/`source_2` (36 § avtalslagen), `RESEARCH_NEED_CONCURRENCY=1`,
    `RESEARCH_DOCUMENT_CONCURRENCY=1`
  - DB: `backend/data/live_v5.sqlite` (fresh from empty → `alembic upgrade head`
    = `192_drop_graph_tables`, customer 1, 195 prompt fields, 0 documents before
    the run)
  - OverGraph: `/tmp/live-v5-overgraph`; lexical index: `/tmp/live-v5-index`
- **Fake/parity quality note**: fake and parity layers use **fake embeddings
  (constant vector)** — quality is **not meaningful** there. Only legacy fake
  guards/parity are authoritative in those layers.
- v1 cutover artifact: `a00ba5659b204dd12c2c58b9c76d4a04630e4a4ae19aa9e4dad8e363b82fdd6f`

## 1. Main result — per arm (successful samples)

The failed sample (`swe_a` / `source_2` / repeat 0) is listed separately in
section 2 and is excluded from these aggregates and from ranking.

| Arm | n | Wall mean (ms) | Wall median (ms) | Wall min–max (ms) | Tokens mean | LLM calls | Evidence found | not_found | error | Needs | Assessments | Completeness | Synthesis rubric | get_document | Jev routes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 4 | 166 731.9 | 172 788.7 | 109 878.6–211 471.6 | 501 902.0 | 62–96 | 185 | 77 | 7 | 56 | 11 insufficient | 0 pass | 0.125 | 25 | 82 |
| A (concurrency 8) | 3 | 124 913.1 | 124 834.1 | 108 120.7–141 784.4 | 451 568.7 | 36–75 | 202 | 53 | 1 | 43 | 8 insufficient | 0 pass | 0.167 | 7 | 36 |
| B (concurrency 16) | 4 | 146 908.2 | 153 974.0 | 78 186.1–201 498.6 | 673 950.8 | 61–120 | 390 | 73 | 9 | 62 | 10 insufficient | 0 pass | 0.146 | 3 | 79 |

Totals over the successful samples: **777 found**, 0 `OperationalError`, 0 index
errors, 0 `assessment_error`. All successful attempts are `ready` with frozen
evidence sets. Stop reasons: `max_iterations` 7, `max_needs` 4.

MCP per successful arm: baseline resolve 71 / search 53 / get_incoming 53 /
get_document 25; A 55 / 32 / 32 / 7; B 70 / 58 / 57 / 3. Jev-noul values:
760 / 312 / 720.

## 2. Failed sample and sample-level notes

- `swe_a` / `source_2` / repeat 0: `status=failed`, attempt
  `9f7bacb9d1f9482d877047d8fcad9db2`; **75 found**, 46 not_found, 2 error;
  two assessments (both insufficient). It is recorded in `failed_samples` and
  excluded from ranking; `wall_ms` 140 195.6 ms.
- Failure surfaced as generic `ResearchExecutionError: Attempt … research
  failed`; the underlying cause was not preserved by the production error path
  (task-23). This is why the sample is not used for quality claims even though
  most of its measurement data exists.
- `lexical_index` per sample: 11× `ready` (`already-open`) and 1× `empty_graph`
  on the first sample (deferred on an empty graph, expected). No index-related
  failures.
- Completeness is empty for every sample: `loop_decision.decide_after_assessment`
  stops with `no_novel_followups` when the local assessment is `insufficient`
  and follow-up budget is exhausted; the global completeness reviewer only runs
  after `sufficient`. This is expected for this measurement — it does not
  indicate a bug.

## 3. Per-stage timings per arm (sum ms / calls; median per sample in parentheses)

Stage sums can exceed wall time under concurrency.

| Arm | lexical_index | planning | source_fetch | assessment | follow_up | persist | quality_persist |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 4 058.2 / 4 (1 154.0) | 3 870.3 / 1 | 496 963.4 / 51 (131 068.4) | 107 386.1 / 62 (28 033.8) | 46 128.4 / 10 (11 196.3) | 79 949.7 / 11 (20 631.0) | 3 909.9 / 52 (957.2) |
| A | 3 158.3 / 3 (1 132.5) | — | 212 468.8 / 40 (64 666.0) | 106 120.5 / 45 (36 280.3) | 44 176.0 / 8 (13 762.5) | 78 337.3 / 8 (26 413.7) | 5 360.3 / 40 (1 715.0) |
| B | 4 632.9 / 4 (1 162.1) | — | 577 750.7 / 56 (156 655.0) | 203 388.3 / 73 (49 684.3) | 61 771.2 / 10 (15 168.6) | 139 121.5 / 10 (35 136.8) | 14 221.9 / 58 (3 507.1) |

Knowledge reuse, Jev/relevance and freeze did not produce stage timers in this
run (empty graph-driven reuse was not exercised; freeze is folded into persist
via `finish_research_wave`). `lexical_index` is the new harness stage: it
opens/reconciles the shared Tantivy index before each sample; median ≈1.15 s
per sample.

## 4. Ranking (observational, not a gate)

| Arm | Evidence coverage | Assessment sufficient | Completeness | Synthesis rubric | Mean wall (ms) | Label |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 0.6903 | 0.0 | 0.0 | 0.125 | 166 731.9 | comparable |
| A | 0.7948 | 0.0 | 0.0 | 0.1667 | 124 913.1 | comparable |
| B | 0.8313 | 0.0 | 0.0 | 0.1458 | 146 908.2 | comparable |

- A is the fastest arm (124.9 s mean) and has somewhat higher evidence
  coverage and synthesis rubric than baseline; B has the highest evidence
  coverage but is slower and uses the most tokens.
- **No arm has sufficient assessments or a completeness pass**, and the
  synthesis rubric is low across the board (0.125–0.167 of 1.0). The arms are
  therefore all labelled **"comparable"**: the data does not support a quality
  winner, and the faster arm is **not** classified as better.

## 5. History — how the measurement got here

| Run | Catalog (`data/research_swe/`) | Harness sha | Commit | Result |
| --- | --- | --- | --- | --- |
| Pre-measurement 12 runs | `v2-caafc8706a75-20261022T062521Z` | `caafc870…` | `e6a40a92…` | 12 attempts ready; **0 found**; 44/213 evidence items `OperationalError: database is locked`; concurrency 8. |
| Diagnostic #1 | `v2-caafc8706a75-20261022T064321Z` | `caafc870…` | `e6a40a92…` | 3 samples; 0 found; 26 `OperationalError` events; source_fetch 11–25 s/call. |
| Diagnostic #2 | `v2-ba48eb2a3a7b-20261022T070513Z` | `ba48eb2a…` | `c07fc348…` | 1 sample, concurrency 1: **0 OperationalError**, 0 found; resolve-args were whole English questions. |
| Acceptance (fresh DB) | `v2-ba48eb2a3a7b-20261022T090718Z` | `ba48eb2a…` | `f5a3b85c…` | 1 sample; **17 found**, 0 OperationalError; failed in assessment with context-limit error. |
| Acceptance 2 (fresh DB) | `v2-ef9d502e05d1-20261022T093509Z` | `ef9d502e…` | `9ae2894f…` | 1 sample ready; **24 found**; 0 OperationalError; 16 Jev routes. |
| v3 attempt (full) | `v2-ef9d502e05d1-20261022T093800Z` | `ef9d502e…` | `9ae2894f…` | 12 samples: 1 ready, 11 child failures (`lexical index is not open`). Aborted as a measurement. |
| **v5 (main)** | **`v2-c39af043803c-20261022T100637Z`** | **`c39af043…`** | **`fd708201…`** | **12 samples: 11 ready + 1 failed**; 777 found; 0 OperationalError; 0 index errors; 0 assessment errors. |

The v4 setup was superseded by the production lexical-index lifecycle
(`fd708201`, PR #421) before completion; it produced no reportable artifact.
No live run was retried after v5.

## 6. What the live run now shows

- **Retrieval works end-to-end.** 777 found evidence items across the 11
  successful samples; resolve args are valid legal citations (e.g.
  `36 § avtalslagen`, `prop. 1975/76:81`, `prop. 1994/95:17`, `bet. 2002/03:LU4`,
  `SOU 1974:83`); `get_document` was executed (25/7/3 per arm) and Jev passage
  routing ran (82/36/79 routes).
- **Where the time goes:** `source_fetch` dominates (mean wall 124–167 s per
  arm), with `assessment` (106–203 s aggregate), `persist` (78–139 s) and
  `follow_up` (44–62 s) next; `lexical_index` is cheap (~1.15 s/sample),
  planning and quality persist are small.
- **What cannot be measured yet:** quality. There are **0 sufficient
  assessments**, **0 completeness passes**, and the synthesis rubric is low
  (0.125–0.167). The evidence coverage differences (0.69–0.83) are not enough
  to call a winner. Quality measurement requires the assessment/completeness
  path to become meaningful (task-23 will at least preserve future failure
  causes; a clean v6 run is optional if cheap).

## 7. Scope limits

- Fake mode cannot exercise cancellation, lease-lost or crash/resume; those
  require the running worker/lease seam and are verified by the task-5 wiring
  test.
- Retry: neither the phase-2 loop nor the SWE bridge retries. SWE rejects
  `retry` in preflight; timeout is the only time control and is the parity
  scope for timing-dependent behaviour.
- Live quality is non-deterministic and depends on external legal retrieval; it
  is a separate observational measurement, not a cutover gate.
- Fake/parity layers use fake embeddings (constant vector); their quality is
  not meaningful — only gates and parity are authoritative there.
