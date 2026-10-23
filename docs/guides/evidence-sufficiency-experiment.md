# Evidence sufficiency experiment

Opt-in only. Production `LlmResearchAssessor` is unchanged
([PR #420](https://github.com/kajmund/socialism/pull/420)).

Policy: [workflow-first-execution.md](../architecture/workflow-first-execution.md).
Reuse audit: [evidence-sufficiency-reuse-audit.md](../architecture/evidence-sufficiency-reuse-audit.md).

## What it measures

Whether a workflow-first assessor can judge a **complete** EvidenceSet
on `WorkflowRunner` (same map/join pattern as `swe_bridge`) without the
PR #420 character window, and whether obligation + independence gates
remove false-sufficient verdicts on tail counterevidence, late evidence,
and the published 567 k-character case.

## How to run

From `backend/`:

```bash
uv run python scripts/benchmark_evidence_sufficiency.py
```

The harness uses **scripted Jev** (no network). Those scores are a
closed judge, not live model quality. The PR #420 budgeted encoder is
the Cerebras baseline stand-in: text the encoder omits cannot be judged.
A separate `live` object reports `unavailable` when `TYPESAFE_API_KEY`
or `CEREBRAS_API_KEY` is missing. The script does not invent live scores.

## Golden cases

| id | Trap | Expected draft | Expected status |
| -- | ---- | -------------- | --------------- |
| `short_sufficient` | One independent supporting source; obligations known | sufficient | sufficient |
| `no_support` | Found item, no factual support | insufficient | insufficient |
| `tail_counterevidence` | Support in the head; contradiction after the 1 500-character trim | insufficient | uncertain |
| `late_evidence` | Many large found items; only the last item contradicts | insufficient | uncertain |
| `large_567k` | 33-item large-excerpt payload with a tail contradiction | insufficient | uncertain |
| `multi_obligation` | Two required source types; only one present | insufficient | insufficient |
| `missing_source_type` | Required `swedish_law`; evidence is `case_knowledge` | insufficient | insufficient |
| `unknown_requirements` | Empty `source_types` | insufficient | uncertain |
| `duplicate_sources` | Five copies, one `independence_key`, corroboration required | insufficient | insufficient |
| `later_wave_contradiction` | Support then a later-wave contradiction | insufficient | uncertain |
| `adversarial_empty` | Found item with empty excerpt | insufficient | insufficient |

Conflict cases (A2/A3), reported separately from the four-case A0 benchmark:

| id | Mechanism | Expected draft | Expected status |
| -- | --------- | -------------- | --------------- |
| `duplicate_contradiction` | Contradiction with duplicate score 0.89 | insufficient | uncertain |
| `independent_contradiction` | Two independent sources, one contradicts | insufficient | uncertain |
| `compatible_periods` | 3 months 2024 vs 6 months 2026, disjoint validity | sufficient | sufficient |
| `compatible_entities` | Different contracts/entities with different values | sufficient | sufficient |
| `unknown_counterpart` | One flagged passage, no counterpart | insufficient | uncertain |
| `pair_over_budget` | A3 only: required pair does not fit the pair budget | insufficient | uncertain |

`scripted_benchmark_cases()` stays the four-case A0 set. The conflict cases live
in `conflict_benchmark_cases()` (five; `pair_over_budget` is A3-only) and in
`all_golden_cases()`. Two fixture-only seams make them runnable through the
whole SWE workflow: per-evidence score overrides in `scripted.py` (test double,
not model quality) and the optional `counterparts` mapping passed from
`run_experiment` to `evaluation_jobs`. Neither is imported by production.

Contradiction is preserved and is not final insufficiency. The product
draft is fail-closed (`sufficient` or `insufficient`).

## Metrics

Scripted and live reports are labeled separately.

| Metric | Meaning |
| ------ | ------- |
| accuracy | Share of cases whose **draft** matches the label |
| false_sufficient_rate | Sufficient predictions among cases labeled insufficient |
| confusion | true/false sufficient and insufficient counts |
| coverage | Characters actually judged / characters in the EvidenceSet |
| latency_ms | Wall time for that path |
| cost | Jev calls, LLM calls, input characters |

Published PR #420 measurement (not re-run here): **567 673 → 56 443**
characters on Cerebras `gpt-oss-120b` with an 8 192-token output cap.
See `tests/fixtures/sufficiency_experiment/pr420_cerebras_baseline.json`.

## Contradiction trace

The live metrics say *that* the two traps fail, not *where*. The opt-in trace
(`include_trace=True` on `run_benchmark` / `measure_live_models`) keeps every
judged passage with its NOUL scores, the Jev route answers, the route state, the
obligation states and the gate reasons. Run it from `backend/`:

```bash
uv run python scripts/trace_evidence_sufficiency.py \
  --out tests/integration/baselines/sufficiency-contradiction-trace-v1.json
```

Findings and the three independent failure layers:
[evidence-sufficiency-contradiction-trace.md](evidence-sufficiency-contradiction-trace.md).
Proposed comparison with a narrative pre-check:
[evidence-sufficiency-narrative-precheck.md](../architecture/evidence-sufficiency-narrative-precheck.md).

## Conflict records (A2)

A2 separates redundancy from contradiction. A conflict record has one status:

| Status | Meaning |
| ------ | ------- |
| `unresolved` | Possible or confirmed conflict that is not cleared |
| `resolved` | Real conflict with an explicitly verified resolution |
| `not_applicable` | The claims apply to different periods/entities/definitions and do not contradict |

Only a typed, verifiable reason can clear a conflict. The rules read flat
`provenance` keys on the evidence item: `valid_from`/`valid_to` (ISO-8601),
`entity_id`, `definition_id`, and `superseded_by` (evidence id). Disjoint
validity periods, distinct entities and distinct definitions give
`not_applicable`; an explicit `superseded_by` gives `resolved`. A conflict with
no identified counterpart is never resolved or shown inapplicable. A duplicate
score, relevance score, source count, same-document relation or age alone never
resolves anything, and `independence_key` remains the only basis for counting
independent sources. Unresolved conflicts keep the need `uncertain` and block
`sufficient`; there is no conflict-resolution subworkflow.

Counterfactual replay on the frozen live trace forces the signal passages to a
0.95 contradiction while keeping the measured duplicate scores. It proves the
forced conflict survives a 0.89 duplicate score instead of being dismissed.
Run from `backend/`:

```bash
uv run python scripts/replay_sufficiency_conflicts.py
```

Artifact: `tests/integration/baselines/sufficiency-conflict-replay-v1.json`.
Two of the cases (`tail_counterevidence` 0.61, `late_evidence` 0.89 duplicate)
now stay unresolved and `insufficient`. This is a replay over measured scores,
not a new live run.

## Claim candidates (A3)

A3 starts with deterministic **claim candidates**, not extracted atomic facts.
`claims.py` splits each judged passage on sentence boundaries (with a legal
abbreviation guard, so `NJA 2005 s. 142.` is not split), and keeps the exact
slice. A multi-clause sentence stays one candidate: the Jev pair comparison in
the next step decides what it asserts. `extraction_method` is
`deterministic_segment`.

| Status | Meaning |
| ------ | ------- |
| `extracted` | Candidate that may be compared |
| `uncertain` | Exact text identified, but not safe to compare (`too_short`, `question`, `too_long`, `citation_only`) |
| `unprocessed` | Budget prevented processing |

Invariants: `passage.text[start:end] == claim.text` for every candidate.
`normalized_text`/`canonical_key` are for search and grouping only — they never
replace the stored text, merge source occurrences or affect `independence_key`.
`entity_id`, `valid_from`/`valid_to` and `definition_id` are copied only from
verifiable provenance and are never guessed from the text.

`ClaimCoverage` reports candidates, extracted/uncertain/unprocessed counts,
candidates per evidence item (the TextUnit analogue in this experiment) and per
need, plus whether coverage is complete. The caps are safety limits, not goals:
`min_claim_chars`, `max_claim_chars`, `min_claim_words` and
`max_claims_per_need`. Hitting the per-need cap marks coverage incomplete, adds
`claim_coverage_incomplete` to the gate and blocks `sufficient`. Uncertain
candidates stay visible in the coverage counts; they are never treated as
verified and they do not consume the comparison budget. No model call happens
during extraction.

## Pair candidates (A3)

Candidate generation is measured separately from Jev judgement. Three
strategies propose claim pairs and each reports recall **before** and **after**
the per-need budget (`max_pairs_per_need=40`):

- **Deterministic**: shared `entity_id`/`definition_id`, shared content tokens
  weighted by rarity, and overlap with the need question. `canonical_key`
  equality only down-weights a pair; it never excludes one. Temporal metadata is
  a feature, not a filter.
- **Embeddings**: top-`embedding_neighbors` cosine neighbours per claim.
- **Hybrid**: union of both candidate sets. A pair found by both keeps both
  sources and the combined score, so it can survive the budget.

Frozen facit: `tests/integration/baselines/pair-gold-v1.json` with
`candidate_pairs` (must be proposed) and `contradiction_pairs` (Jev facit).
`unknown_counterpart` is a negative control and is excluded from recall
aggregates.

Run from `backend/` (add `--embeddings` for B/C):

```bash
uv run python scripts/measure_pair_recall.py --embeddings
```

Artifact: `tests/integration/baselines/pair-recall-v1.json`. Measured with
`text-embedding-3-large`:

| Case | A rank | A selected | B rank | B selected | C rank | C selected |
| ---- | -----: | ---------: | -----: | ---------: | -----: | ---------: |
| `duplicate_contradiction` | 1 | yes | 2 | yes | 1 | yes |
| `independent_contradiction` | 1 | yes | 1 | yes | 1 | yes |
| `compatible_periods` | 1 | yes | 1 | yes | 1 | yes |
| `compatible_entities` | 1 | yes | 1 | yes | 1 | yes |
| `tail_claim_contradiction` | 1 | yes | **340** | **no** | 1 | yes |

Summary over the five positive cases: A recall 1.00/1.00, B 1.00/0.80, C
1.00/1.00 (before/after budget). A selects 44 pairs with 0 embedding calls; B
and C select 48 with 5 embedding calls. The tail case is the point: embeddings
find the pair before the budget (recall 1.00) but rank it 340, so it is sorted
out; the hybrid keeps it at rank 1. No Jev call is made — selected pairs are the
Jev-call budget for the next step.

The easy tail case shares attribute tokens by design. A harder semantic tail
case (contradiction worded without token overlap) is deferred to the next
benchmark version.

## Pair judgement (A3)

Jev detects possible contradictions; A2 decides whether a detected conflict is
material and resolvable; SWE refuses `sufficient` while a required pair is
uncertain or unevaluated. Pair evaluation runs as `prepare_pairs → pair_jobs
(map) → aggregate_pairs` in the main workflow.

Protocol (`pair_eval.py`): one `relation` choice with `CONTRADICTS`,
`COMPATIBLE`, `SCOPE_DIFFERENCE` and `INSUFFICIENT`. Each call receives both
claims, their full passages and provenance metadata, capped at
`max_pair_state_chars=6000`; an over-budget pair is skipped, never clipped.
Concurrency 8, timeout 5 s, and `max_pair_jev_calls` bound the run.

| Outcome | Result |
| ------- | ------ |
| `CONTRADICTS` | conflict record; A2 metadata may still make it `not_applicable`/`resolved`, otherwise `unresolved` |
| `SCOPE_DIFFERENCE` with verifiable metadata | `not_applicable` |
| `SCOPE_DIFFERENCE` without verifiable metadata | `unresolved` |
| `INSUFFICIENT` | `uncertain`, counted separately from technical failures |
| `COMPATIBLE` | no conflict record |
| timeout / invalid answer / budget | `unevaluated`, coverage incomplete, fail-closed |

Run from `backend/`:

```bash
uv run python scripts/measure_pair_judgement.py --reps 2 --workflow-timing
```

Artifact: `tests/integration/baselines/pair-judgement-v1.json`. Live results
with resolved model `jev-1.14.0`, two repetitions, all three pair strategies:

| Strategy | Mean recall | Mean precision | False contradictions | Calls | Unevaluated |
| -------- | ----------: | -------------: | -------------------: | ----: | ----------: |
| deterministic | 1.00 | 1.00 | 0 | 88 | 1 (timeout) |
| embeddings | 0.67 | 0.50 | 4 | 96 | 0 |
| hybrid | 1.00 | 0.67 | 4 | 96 | 0 |

The compatible cases were judged `SCOPE_DIFFERENCE` and resolved by A2 metadata,
so they produced no false contradictions. The deterministic and hybrid strategies
found the tail contradiction; embeddings-only missed it on judgement. The
embeddings strategies also paired the extra `Avgörandet gäller ett annat avtal.`
claim with the support claim and Jev called it `CONTRADICTS`, which is the
precision cost visible above. One deterministic pair timed out; it is reported
as `unevaluated` and blocks `sufficient` instead of disappearing.

Wall time is Jev-bound. The deterministic end-to-end timing shows ~650–750 ms
for four-call cases and 2 345 ms for the 49-call tail case at concurrency 8;
summed Jev latency exceeds wall time because calls run concurrently
(`workflow_timing` in the artifact).

Default `pair_strategy` is `deterministic`; embeddings and hybrid need an
injected embedding provider. No live model is used in CI.

## Package

`app.services.research.sufficiency_experiment` — not imported by
`build_llm_research_assessor`. Execution is `SufficiencyLoop` →
`WorkflowRunner.run`.
