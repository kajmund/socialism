# Research SWE experiment

Status: placeholder. The frozen harness
(`backend/scripts/benchmark_research_swe.py`) regenerates this report from the
gated, frozen measurement run:

```bash
cd backend
uv run python scripts/benchmark_research_swe.py --runs 3 --repeats 6 \
  --questions 2 --needs 16 --fake-latency-ms 40 --arms baseline,swe_a,swe_b --strict
```

The generated report contains the metadata (git HEAD, script sha256, arms,
repeats, concurrency, fake latency, persist flag), the hard gates, the reuse
table, the live observational layer and the cutover-safe winner / fastest-arm
distinction. It measures orchestration in fake mode, not research quality.
