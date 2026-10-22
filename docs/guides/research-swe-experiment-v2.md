# Research SWE experiment v2 — live quality, per-stage timings and diagnostics

**Observational instrumentation harness.** The v1 artifact
(`benchmark_research_swe.py`, frozen sha `a00ba565…`, n=8) remains the cutover
basis; v2 does not replace its gates. This document is a **hand-restored
artifact** from the raw runs (the frozen harness overwrote the generated live
section with diagnostic runs); it records the full 12-run live measurement as
the main artifact and keeps the diagnostic runs as separate dated history.

## Metadata

- Main live artifact: `data/research_swe/v2-caafc8706a75-20261022T062521Z`
  - harness sha256: `caafc8706a753898d88391d18f6a966b4ca279709f28d4870a0c2432056b9373`
  - git commit: `e6a40a923efb2e9dfcaf3b78503cc70365321f1a`
- Frozen harness after diagnostics: sha256
  `ba48eb2a3a7bdc1755184f43412a8af9570d04a9ddbb5b9fe908e700c40efc63`,
  commit `c07fc348407c50e9fdf3aad3fcd50c5db08c6403`
- Fake/parity layers were measured in freeze #4:
  `data/research_swe/v2-528d26d45dfa-20261021T234946Z` (harness sha
  `528d26d4…`, n=8 fake runs) — see section 1.
- v1 cutover artifact: `a00ba5659b204dd12c2c58b9c76d4a04630e4a4ae19aa9e4dad8e363b82fdd6f`

**Fake/parity quality note:** fake and parity layers use **fake embeddings
(constant vector)** — quality is **not meaningful** there. Only fake guards and
behavioural parity are authoritative in those layers.

## 1. Fake and parity layers (reference, freeze #4)

Critical-path/peak-concurrency instrumentation and behavioural parity were
measured in freeze #4 (`v2-528d26d45dfa-20261021T234946Z`):
fake layer = 8 independent runs × 6 repeats × 2 questions × 3 arms (16 needs,
40 ms fake latency; 288 cold samples, 96/arm); provider peak concurrency 8 for
baseline/A and 16 for B; fake guards passed; parity 6/6 scenarios equal,
including `follow_up_wave`. Those are not re-listed here because the current
artifacts are live-only.

## 2. Live quality — main artifact (12 runs)

**Environment:** healthy on the measurement host. `lagen.nu`/MCP reachable
(`initialize`/`tools/list` 200), OpenAI embeddings 200 (3072 dims), Cerebras
chat 200. Runs use **production embeddings** (`graph_embedding_cache` 5 001
rows, `text-embedding-3-large`, 3072 dims). Jev thresholds are correct on the
production embeddings; the failure is not embedding/Jev driven.

**Fixture:** 2 eval questions (`source_1`, `source_2`, 36 § avtalslagen) ×
3 arms × 2 repeats = **12 production attempts**; temp SQLite DB on alembic
head; `research_need_concurrency=8` (default); 44/213 evidence items carried
`OperationalError: database is locked` (measured environment contention);
source-fetch calls took ≈7–10 s each.

| Arm | Samples | Wall mean (ms) | Wall median (ms) | Wall min–max (ms) | Tokens mean | LLM calls | Evidence | Needs | Assessments | Completeness | Synthesis rubric | Label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 4 | 66 629.6 | 71 862.9 | 43 663.1–79 129.4 | 156 518.5 | 26–46 | 43 not_found, 14 error, **0 found** | 49 | 10 insufficient, 0 sufficient | 0 pass | 0.0 | comparable |
| A (concurrency 8) | 4 | 57 753.5 | 63 332.3 | 24 538.5–79 810.8 | 167 513.5 | 28–54 | 65 not_found, 13 error, **0 found** | 61 | 12 insufficient, 0 sufficient | 0 pass | 0.0 | comparable |
| B (concurrency 16) | 4 | 83 775.1 | 97 130.4 | 22 771.6–118 068.1 | 226 682.5 | 26–67 | 58 not_found, 20 error, **0 found** | 63 | 11 insufficient, 0 sufficient | 0 pass | 0.0 | comparable |

All 12 attempts finished `ready` with frozen evidence sets. Stop reasons:
`max_iterations` 10, `max_needs` 1, `no_novel_followups` 1.

**Per-stage timings (sum ms / calls across the arm's 4 samples).** Stage sums
can exceed wall time under concurrency.

| Arm | Planning | Source fetch | Assessment | Follow-up | Quality persist | Wave persist |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 15 290.2 / 4 | 355 531.4 / 45 | 0.52 / 14 | 17 165.7 / 7 | 610.4 / 45 | 18 086.7 / 10 |
| A | 13 511.8 / 4 | 413 262.5 / 57 | 0.64 / 16 | 19 978.7 / 8 | 814.6 / 57 | 21 176.9 / 12 |
| B | 13 079.8 / 4 | 628 073.5 / 59 | 0.68 / 15 | 17 800.0 / 7 | 808.5 / 59 | 18 964.9 / 11 |

`source_fetch` dominates the real time; planning/follow-up/persist are tens of
seconds in aggregate, assessment/quality persist are negligible. Knowledge
reuse, Jev/relevance and completeness/freeze timers produced 0 calls in this
run (empty graph in the temp DB, no graph candidates, budget-stop before a
global completeness pass; `research_frozen_ready`=12 confirms freeze happened
inside `finish_research_wave`/persist). Synthesis is **not a separate stage**
(the loop ends at the frozen EvidenceSet; synthesis quality is judged
post-hoc).

**Quality conclusion:** every arm has **0 found evidence**, 0 sufficient
assessments, no completeness pass, synthesis rubric 0 and LLM verdicts that say
"no evidence". The arms are therefore all **"comparable"**; no quality ranking
is made, and the faster mean wall time of A is not evidence of better quality.

Judge prompt/verdict and per-sample evidence are saved in
`live/live-*.json` next to `live/live-results.json`.

## 3. Diagnostic runs (live)

### (a) 12-run environment diagnosis (production embeddings, concurrency 8)

The main artifact above: 12 attempts, production embeddings, 8 concurrent
needs, 44/213 evidence items with `OperationalError: database is locked`,
source-fetch ≈7–10 s/call, 0 found. Catalog
`v2-caafc8706a75-20261022T062521Z`, harness sha `caafc870…`, commit
`e6a40a92…`. This established that the lock contention is a measurement-
environment problem, not a code path.

### (b) Diagnostic run #1 (3 samples)

Catalog `data/research_swe/v2-caafc8706a75-20261022T064321Z`, harness sha
`caafc870…`, commit `e6a40a92…`. Command: `--mode live --live-questions 1
--live-repeats 1 --arms baseline` (frozen harness at the time still iterated
all arms, so 3 samples: baseline/A/B × `source_1` × repeat 0).

| Arm | Wall (ms) | Tokens | LLM calls | Evidence | Source fetch |
| --- | --- | --- | --- | --- | --- |
| baseline | 137 642.8 | 347 396 | 65 | 13 not_found, 10 error, 0 found | 15 calls, 25.1 s/call |
| A | 91 265.4 | 241 797 | 49 | 17 not_found, 7 error, 0 found | 15 calls, 11.4 s/call |
| B | 116 304.9 | 394 530 | 80 | 17 not_found, 9 error, 0 found | 15 calls, 16.8 s/call |

Errors were `OperationalError: research source failed` (26 events across arms)
and not_found categories `irrelevant_relation`/`resolve_no_document`. MCP tool
counters were not yet added to the harness at this freeze, so per-tool counts
are absent here. No route/Jev passage stage was reached.

### (c) Diagnostic run #2 (1 sample, concurrency 1)

Catalog `data/research_swe/v2-ba48eb2a3a7b-20261022T070513Z`, harness sha
`ba48eb2a…`, commit `c07fc348…`. Command: `--mode live --live-questions 1
--live-repeats 1 --arms baseline --live-concurrency 1
--live-db-path data/live_diag.sqlite`; DB at alembic head
`192_drop_graph_tables`, customer 1 (`devbrains`), module `dd`, 195 prompt
fields; `RESEARCH_NEED_CONCURRENCY=1` and
`RESEARCH_DOCUMENT_CONCURRENCY=1` for the live child.

| Metric | Value |
| --- | --- |
| Attempts | 1 (baseline, `source_1`, repeat 0) |
| **OperationalError** | **0** |
| MCP calls | **29** total: resolve 14, search 15, get_incoming 0, **get_document 0** |
| Resolve args | 14/14 = whole English need questions (e.g. "What is the exact wording of § 36 of the Swedish Contracts Act…") |
| Search queries | truncated English fragments (e.g. `"What the exact wording Swedish Contracts"`, `"What the exact"`) |
| Evidence | 16 needs, 19 evidence items: **found 0**, not_found 19, error 0 |
| Failure categories | resolve_no_document 8, irrelevant_relation 6, empty Supabase 4, search_no_hit 1 |
| Route/Jev | never reached: seed_ids/noul empty (no get_document) |
| Wall / tokens / LLM | 38 922.7 ms / 70 334 / 29 |
| Stages | planning 3 862.2 ms; source_fetch 22 594.0 ms / 15 calls (≈1.5 s/call); follow_up 11 888.4 ms; persist 12 176.8 ms; quality_persist 192.3 ms; assessment 0.33 ms |

Child stderr contained only a `storage3` URL warning; no exceptions. The
`mcp_diagnostics.failures` list is empty.

**Lock vs retrieval:** the diagnostic reduces OperationalError **44 → 0** and
source-fetch from **7–25 s to ≈1.5 s/call**, proving the contention was the
SQLite temp environment. It does **not** recover evidence: 0 found remains,
now attributable to question format (see below).

## 4. Why live measured 0 found

Language evidence from the raw artifacts (`samples[].needs[]`,
`samples[].mcp_diagnostics`):

1. **English is already in the planner output.** In diagnostic #2,
   `needs[].question` is English for all initial needs `N1–N5` and all derived
   needs (`N1a`, `N1b`, `N2a` … `N7`), while `research-main` (the original
   question) is Swedish. 5/6 initial needs are English. The language switch
   therefore happens **before** the source stage.
2. **The source stage receives the need text unchanged.** In diagnostic #2,
   **14/14** `resolve_args` are exactly equal to `needs[].question` — whole
   English questions, not `"36 § avtalslagen"`. `resolve_no_document` follows
   directly from that format.
3. **Search is a downstream truncation, not the switch.** The source query
   builder collapses the English questions to fragments
   (`"What the exact wording Swedish Contracts"`, `"What the exact"`), so
   `search_no_hit`/`irrelevant_relation` follow. It cannot rescue the already
   English question format.
4. **The planner prompt has no language/citation guard.**
   `research.planner.system` is loaded with `language="sv"` via
   `build_llm_research_planner`, but the prompt text only says to decompose the
   objective into narrow needs; it has no explicit "answer in Swedish" or
   legal-citation-format instruction, and there is no deterministic guard that
   rejects non-Swedish or non-citation-formatted needs. The result is
   **nondeterministic planner output**: 12-runs had Swedish needs in 11/14
   samples and English in 3 (swe_a source_1 rep0, swe_b source_1 rep0,
   swe_b source_2 rep0); diagnostic #1 had Swedish in all 3; diagnostic #2 had
   English in 5/6 initial needs and all derived needs. `research-main` is
   Swedish in every sample.
5. **Consequence chain:** English planner needs → invalid resolve arguments
   (`resolve_no_document`) and truncated search queries (`search_no_hit`) →
   selection rejects candidates (`irrelevant_relation`) → 0 `get_document` →
   no passage routing/Jev (`seed_ids`/`noul` empty) → no found evidence →
   assessments insufficient, no completeness, synthesis rubric 0.

## 5. Status and conclusion

- Live quality measurement is **blocked by the retrieval question format
  (task-13)**, not by SWE, Jev or embeddings. The planner/normalizer output
  language is nondeterministic and there is no deterministic guard; the source
  stage cannot repair an English whole question into a valid legal citation.
- Live remains an observational layer: it never affects the exit code and no
  quality ranking is performed. All arms have equal (zero) evidence quality, so
  the faster arm is **not** classified as better.
- Fake/parity layers use fake embeddings (constant vector); their quality is
  not meaningful — only gates and behavioural parity are authoritative there.
- Once task-13 fixes planner/normalizer language and citation format, a live
  v3 run (`--live-concurrency 1`, prepared DB at head) can be evaluated with
  the same harness; measurement must keep recording `needs[].question` per
  need, which freeze #6 does.

## 6. Scope limits

- Fake mode cannot exercise cancellation, lease-lost or crash/resume; those
  require the running worker/lease seam and are verified by the task-5 wiring
  test.
- Retry: neither the phase-2 loop nor the SWE bridge retries. SWE rejects
  `retry` in preflight; timeout is the only time control and is the parity
  scope for timing-dependent behaviour.
- Live quality is non-deterministic and depends on external legal retrieval;
  it is a separate observational measurement, not a cutover gate.
