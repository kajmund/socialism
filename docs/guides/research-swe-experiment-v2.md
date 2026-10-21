# Research SWE experiment v2 — critical path, concurrency, parity, live quality

Status: placeholder. The frozen v2 harness
(`backend/scripts/benchmark_research_swe_v2.py`) regenerates this report from a
frozen measurement:

```bash
cd backend
uv run python scripts/benchmark_research_swe_v2.py --mode all \
  --runs 8 --repeats 6 --questions 2 --needs 16 --fake-latency-ms 40 \
  --arms baseline,swe_a,swe_b --live-questions 2 --live-repeats 2
```

**Sample sizes per layer (documented in the generated report metadata):**

- **fake layer**: 8 independent runs × 6 interleaved repeats × 2 questions ×
  3 arms (16 needs, 40 ms fake latency) = 288 cold samples, 96 per arm.
- **live layer** (observational): 2 questions × 3 arms × 2 repeats = 12
  production attempts.

The harness has three observational layers:

1. **Fake instrumentation** — wall time, handler wait sum, busy-union critical
   path, peak concurrent handlers, overhead, per-need and per-SWE-node timings,
   per-run medians and paired ratio dispersion (min/max/mean/sd, per question).
2. **Behavioural parity** — differential fake scenarios (provider error,
   not_found, per-need timeout, follow-up wave, empty plan, freeze/status,
   progress events) and the explicit retry/timeout statement; cancellation,
   lease-lost and crash/resume are listed as task-5 wiring-test-only.
3. **Live quality** — app-lifecycle-wired production runs on a temp DB at head:
   evidence coverage, successful needs, assessment/completeness, an explicit
   synthesis rubric with saved judge artifact, tokens/time and dispersion.
   Observational and non-deterministic; live failures are captured as artifacts
   and never affect the harness exit code.

The v1 artifact (`benchmark_research_swe.py`, frozen sha `a00ba565…`, n=8)
remains the cutover basis. v2 does not replace its gates: exit is decided by
fake guards and behavioural parity only.
