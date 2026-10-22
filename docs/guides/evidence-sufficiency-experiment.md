# Evidence sufficiency experiment

Opt-in only. Production `LlmResearchAssessor` is unchanged
([PR #420](https://github.com/kajmund/socialism/pull/420)).

Policy: [workflow-first-execution.md](../architecture/workflow-first-execution.md).

## What it measures

Whether a workflow-first assessor can judge a **complete** EvidenceSet
without the PR #420 character window, and whether that removes
false-sufficient verdicts on tail counterevidence, late evidence, and
the published 567 k-character case.

## How to run

From `backend/`:

```bash
uv run python scripts/benchmark_evidence_sufficiency.py
```

Writes JSON to stdout. The harness uses scripted Jev (no network) and
the PR #420 budgeted encoder as the Cerebras baseline stand-in: text
the encoder omits cannot be judged. That is the frozen comparison.
Live Cerebras / live Jev are not this script's path.

## Golden cases

| id | Trap | Expected |
| -- | ---- | -------- |
| `tail_counterevidence` | Support in the head; contradiction after the 1 500-character trim | insufficient |
| `late_evidence` | Many large found items; only the last item contradicts | insufficient |
| `large_567k` | 33-item large-excerpt payload (PR #420 size class) with a tail contradiction on a found item | insufficient |
| `short_sufficient` | Small supporting set, no contradiction | sufficient |

Cases are built in
`app.services.research.sufficiency_experiment.golden`. They are not
checked in as 567 k-character fixtures.

## Metrics

| Metric | Meaning |
| ------ | ------- |
| accuracy | Share of cases whose verdict matches the label |
| false_sufficient_rate | Sufficient predictions among cases labeled insufficient |
| coverage | Characters (or passages) actually judged / characters in the EvidenceSet |
| latency_ms | Wall time for that path |
| cost | Jev calls, LLM calls, input characters |

Published PR #420 measurement (not re-run here): **567 673 → 56 443**
characters on Cerebras `gpt-oss-120b` with an 8 192-token output cap.
See `tests/fixtures/sufficiency_experiment/pr420_cerebras_baseline.json`.

## Package

`app.services.research.sufficiency_experiment` — not imported by
`build_llm_research_assessor`.
