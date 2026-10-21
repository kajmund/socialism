# Research SWE experiment v2 — critical path, concurrency, parity, live quality

**Observational instrumentation harness.** The v1 artifact (`benchmark_research_swe.py`, frozen sha `a00ba565…`, n=8) remains the cutover basis; v2 does not replace its gates.

## Metadata

- git HEAD: `175b2ffea3f829d27fc7dbecfef7e79a554962e3`
- v2 script sha256: `528d26d45dfa8ae874fe3ab8345c83c07463197ec3351a31f9aff1da32f24b90`
- arms: baseline, swe_a, swe_b
- **fake layer**: 8 independent runs x 6 interleaved repeats x 2 questions (need count 16, fake latency 40 ms)
- **live layer** (observational): 2 questions x 3 arms x 2 repeats
- raw data: `/Users/erikfremred/socialism/data/research_swe/v2-528d26d45dfa-20261021T234946Z`

## 1. Critical path and peak concurrency (fake mode)

| Arm | Wall median (per-run medians) | Wall sd | Overhead median | Provider peak (max/median vs expected) | Busy-union median | Sum wait median | Ratio arm/baseline min/max/mean/sd |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (phase-2 wave loop) | 687.1085 | 11.6298 | 274.001 | 8/8.0 vs 8 | 401.4165 | 5713.3985 | 1.0/1.0/1.0/0.0 |
| SWE arm A (same concurrency) | 683.9565 | 13.3899 | 276.285 | 8/8.0 vs 8 | 399.55 | 5674.042 | 0.9714/1.0248/1.0011/0.0195 |
| SWE arm B (wider fan-out) | 691.8495 | 24.3926 | 281.244 | 16/16.0 vs 16 | 396.6995 | 5728.101 | 0.9473/1.0955/1.0139/0.045 |

Per-question wall medians (ms):

| Arm | source_1 | source_2 |
| --- | --- | --- |
| baseline (phase-2 wave loop) | 679.644 | 682.711 |
| SWE arm A (same concurrency) | 680.007 | 681.746 |
| SWE arm B (wider fan-out) | 696.498 | 689.522 |

Critical path is the busy-union of need/handler intervals (actively serialized work); overhead = wall - busy union; parallel gain = sum of intervals - busy union. **Provider peak** counts in-flight `source.research` calls (not coroutine lifetime/semaphore wait); the fixture expects 8 for baseline and arm A (concurrency 8) and 16 for arm B (concurrency 16) with 16 needs. A deviation is listed in results.json and means the fixture did not exercise the intended concurrency. Per-node and per-need details are in results.json.

## 2. Behavioural parity (fake scenarios)

| Scenario | Arms equal to baseline | Baseline status | Baseline stop reason |
| --- | --- | --- | --- |
| provider_error | yes | ready | no_novel_followups |
| not_found | yes | ready | no_novel_followups |
| per_need_timeout | yes | ready | no_novel_followups |
| follow_up_wave | yes | ready | sufficient |
| empty_plan | yes | ready | sufficient |
| freeze_status | yes | ready | sufficient |

Not testable in fake mode (task-5 wiring test):

- `cancellation`: requires the running worker/lease seam; verified by the task-5 wiring test
- `lease_lost`: requires the Postgres CAS lease and a live attempt; verified by the task-5 wiring test
- `crash_resume`: requires the durable OverGraph run store and a real process restart; phase-3/task-5 wiring test

Retry semantics: SWE rejects retry = True; baseline has no retry path; timeout is the only time control and the parity scope.

## 3. Live quality (observational, non-deterministic, not a gate)

Live layer not run in this invocation (**freeze #4 runs fake+parity only**). Live is **environment-blocked** on this measurement host: `https://lagen.nu/mcp` was verified unreachable (curl exit 000 / no connection) while OpenAI/Cerebras respond normally. The live wiring itself works (app lifespan, vector store, OverGraph runtime, judge), but retrieval quality cannot be measured from here. Live must be rerun in a healthy environment before it is used as anything but an observational follow-up; it is never a gate.

> Erratum: the frozen harness template hardcodes "freeze #3" for this sentence. The measured artifact is freeze #4 (`528d26d4…`, commit `175b2ffe…`); this generated line was corrected by hand and the template string will be made neutral the next time the harness changes.

## 4. Scope limits

- Fake mode cannot exercise cancellation, lease-lost or crash/resume; those require the running worker/lease seam and are verified by the task-5 wiring test.
- Retry: neither the phase-2 loop nor the SWE bridge retries. SWE rejects `retry` in preflight; timeout is the only time control and is the parity scope for timing-dependent behaviour.
- Fake mode quality is structural by construction (same domain code); live quality is the only quality observation and is non-deterministic.
