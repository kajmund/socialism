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

## A0 freeze (2026-10-23)

The A0 baseline is frozen from the original PR #422/#426 path at commit
`b55eae13`. No assessment rule was changed for the freeze.

- Artifacts: `tests/integration/baselines/sufficiency-a0-freeze-v1.json`
  (metadata, hashes, variance) plus the two raw repetitions
  `sufficiency-a0-freeze-rep1-raw.json` and `-rep2-raw.json`.
- Requested model `jev-latest`, resolved `jev-1.14.0` in both repetitions.
- Two independent live repetitions, 1 043 Jev attempts each:

| Rep | Accuracy | False-sufficient | Late evidence | Client errors |
| --- | -------: | ---------------: | ------------- | ------------: |
| 1 | 0.75 | 0.33 | insufficient (one failed evaluation) | 2 |
| 2 | 0.50 | 0.67 | sufficient | 2 |

Two transient `JevClientError` calls per repetition are enough to move the
verdict when they land on `late_evidence`; in rep 1 one failed evaluation
became `evaluation_errors` and blocked `sufficient`. A0 is therefore a range,
not a point, and arm comparisons use this frozen pair of runs rather than a
single number. The A1 arm additionally needs the route-authority contract
implemented before A0/A1/A2/A3 can be compared fairly.

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

## First arm comparison (2026-10-23)

Pre-registered run per [measurement-protocol-v1.json](../../backend/tests/integration/baselines/measurement-protocol-v1.json):
10 cases, two repetitions per arm, arm order `A0 → A2 → A3 → A1`.

| Arm | Clean accuracy | False-sufficient | False-insufficient | Jev calls | Detected contradictions |
| --- | -------------: | ---------------: | -----------------: | --------: | ----------------------: |
| A0 | 0.24 | 0.82 | 0.67 | 2 132 | 0 |
| A1 | 0.32 | 0.69 | 0.67 | 2 132 | 0 |
| A2 | 0.26 | 0.77 | 0.67 | 2 132 | 0 |
| A3 | 0.73 | 0.00 | 0.67 | 2 302 | 6 |

Per-trap rep 0:

| Case | A0 | A1 | A2 | A3 |
| --- | --- | --- | --- | --- |
| `tail_counterevidence` | sufficient | sufficient | sufficient | insufficient, contradiction detected |
| `late_evidence` | technical failure | sufficient | sufficient | insufficient, coverage only |
| `duplicate_contradiction` | sufficient | sufficient | sufficient | insufficient, contradiction detected |
| `independent_contradiction` | sufficient | sufficient | sufficient | insufficient, contradiction detected |

The answer to the key question: **A3 solves `tail_counterevidence` through real
pair detection**, and the same for duplicate/independent. **`late_evidence` is
not solved by detection**: no pair conflict was found; it is blocked by
incomplete pair coverage (40-pair budget) and fails closed. That is a
coverage/cost result, not evidence understanding. A3 also turns all rep-0
false-sufficient verdicts into insufficient for +170 Jev calls versus A0 across
both reps (2 302 vs 2 132), with `cost_per_detected_contradiction` 384 calls.

A1's route authority did not change the live traps: the four authority signals
were strong, so the route outcome was `sufficient`; the scripted A0-vs-A1
artifact shows the contract working where the route is actually uncertain.
A2 alone changes nothing without detection.

Pairing: A0 was recorded first. A1 matched 1 060 calls and needed 6 live calls
(reproducibility gaps from the A0 recording, classified as
`reproducibility_error`, not a model error); A2 had the same 6 gaps; A3 had 1 056
matched plus 95 live calls (44 fact-pair calls, new route calls, and the A0
recording gaps). Artifacts: `arm-comparison-v1.json`, `arm-<arm>-2026-10-23.json`
and `jev-cassette-a0-2026-10-23.json`.

Confidence caveat: A1's `confidence` is still the minimum over all five Noul
answers, so `follow_up_change`/`additional_source` can indirectly affect a
sufficient decision through confidence. That indirect path is not displayed in
the arm artifacts yet and should be added to diagnostics in the final plan.

## Route authority (A1)

A1 makes the route outcome count. `sufficient` now requires the deterministic
gate to allow it **and** an explicit `final_outcome=sufficient` on the route.
The four authority signals are `answerable_now`, `material_gap`,
`contradiction` and `confidence` (min Noul confidence over all five answers).
`follow_up_change` and `additional_source` steer further research but never
veto a sufficient verdict, and they cannot override an unmet gate requirement.

Statuses: quality PASS + route sufficient → sufficient; PASS + insufficient →
insufficient; PASS + uncertain → uncertain with an insufficient draft; a FINISH
without an outcome or a rejected sufficient finish fails closed; the
programmatic path is exempt. `status_from_route` owns the mapping.

Arm toggles are experiment-only: `route_authority` (A1),
`legacy_duplicate_resolution` (A0 behaviour) and `pair_judgement` (A3). The
scripted A0-vs-A1 artifact `sufficiency-a1-route-authority-v1.json` records the
three route scenarios with and without the authority switch; no live model is
used.

## Early stop: exhaustive vs existential (2026-10-23)

Two execution modes under the D configuration, two live reps:

- **Exhaustive** evaluates every selected pair inside the 40-pair budget.
- **Existential** stops after the first `CONTRADICTS` pair with verified
  relevance; the outcome is recorded as `EXISTS_BLOCKING_CONFLICT` /
  `CONFLICT_FOUND` / investigation `PARTIAL`, and the underlying evidence status
  is not changed to `SUFFICIENT`.

Artifact: `tests/integration/baselines/early-stop-v1.json`.

| Measure | Exhaustive | Existential |
| --- | ---: | ---: |
| Runs / correct | 16 / 16 | 16 / 16 |
| False-sufficient | 0 | 0 |
| Jev calls | 1 516 | 1 397 |
| Wall time | 125.3 s | 116.9 s |
| Evaluated pairs | 180 | 61 |
| Skipped pair calls | 0 | 119 |
| In-flight calls at stop | 0 | 34 |
| Partial runs | 0 | 4 |
| Invalid/irrelevant stops | 0 | 0 |
| Sufficient presented as partial | 0 | 0 |

Actual avoided Jev calls: **119** (7.8 %), actual wall-time saving **8.4 s**
(6.7 %). Another 34 calls were already in flight when the conflict was found and
were completed, not counted as saved. No stop used a conflict that later
resolved or was irrelevant, and no partial investigation was presented as full
conflict mapping. Production execution is unchanged; no generic predicate
framework was introduced.

## Stop-condition shadow (2026-10-23)

`ExperimentReport.stop_shadow` computes a hypothetical `conflict_confirmed`
stop without changing execution: the first pair verdict `CONTRADICTS` whose
claim pair is an unresolved conflict and whose need has verified relevance.
It records remaining pair calls, estimated calls/latency saved, whether coverage
was complete at that point, and a risk flag. Artifact:
`tests/integration/baselines/stop-shadow-v1.json` (8 cases, two live reps, D
configuration).

| Measure | Result |
| --- | ---: |
| Potential stops | 12 / 16 case-runs |
| Estimated Jev calls saved | 165 |
| Estimated pair latency saved | 44.6 s |
| Stops with complete coverage | 8 |
| Stops with incomplete coverage | 4 (`late_evidence`, `tail_claim_contradiction`) |

The conflict pair was identical in both repetitions for every stopped case, and
no stop relied on a conflict that later resolved. For the "is the evidence
conflicted?" objective the four incomplete-coverage stops are acceptable and
should be labelled incomplete; for "map all conflicts" they must continue. The
execution path and final verdicts are unchanged in this step.

The next step is an explicit early-stop experiment arm (ticket 30), not a
production change.

## Decision diagnostics and the four remaining errors (2026-10-23)

Reports now expose additive `decision_diagnostics.reasons` without changing the
final contract or status semantics: `CONTRADICTION_FOUND`,
`COVERAGE_INCOMPLETE`, `SUPPORT_INCOMPLETE`, `TECHNICAL_FAILURE` and
`SUFFICIENT`, plus unique unresolved conflict ids. Reasons can overlap; a
coverage-negative decision is not reported as a Jev misunderstanding.

Re-running the four wrong B4c decisions (compatible periods/entities, two reps
each) gives the same diagnostic in all four:

| Field | Value |
| --- | --- |
| draft / status | insufficient / uncertain |
| reasons | `SUPPORT_INCOMPLETE` |
| quality reasons | `obligations_unverified` |
| relevance / factual_support | unverified, independent support 0 |
| pair verdict | SCOPE_DIFFERENCE (correct; no conflict) |
| coverage | complete |
| unique conflicts | none |

The remaining four errors are therefore **support-verification/aggregation**
errors, not conflict detection or coverage errors: the pairwise semantic
judgement correctly reports a scope difference, but the relevance and factual
support obligations never verify, so the compatible cases fail closed. The
`narrative_unbound` status is deliberately not counted as a technical failure.

### Ticket 28 root cause: the four fixtures were off-topic

Tracing the stages showed no support-transfer or aggregation bug. The original
compatible fixtures use the plan question "Vilka avgöranden har tillämpat 36 §
avtalslagen?" while their evidence is about `uppsägningstid`. Screening runs on
both passages and returns relevance 0.07–0.11 and support 0.05–0.10, so the
obligations correctly stay unverified. `SCOPE_DIFFERENCE` only says the two
passages do not contradict each other in the compared context; it does not prove
relevance or factual support. The four `insufficient` decisions were correct for
that plan.

Rebuilding the same compatible pairs with the on-topic question "Vilken
uppsägningstid gäller?" and period/entity provenance gives `sufficient` in all
four live repetitions with `SUFFICIENT`, verified relevance/factual support and
no unresolved conflict. No support-engine code or threshold was changed; the
old fixtures are treated as invalid facit for this question, and the on-topic
fixtures are kept separately (`support-on-topic-v1.json`). The separate
stop-condition question remains for ticket 29.

## B4c factorial: generation × ranking (2026-10-23)

Four live arms, two repetitions each, same A3 contract and 40-pair budget:

| Arm | Generation | Ranking | Correct / 26 | False-suff | Candidate Recall | Recall@40 | Unique conflicts | Jev calls | Wall |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | deterministic | current | 16 | 6 | 8 | 6 | 5 | 2 320 | 160.6 s |
| B | hybrid | current | 22 | 0 | 14 | 12 | 9 | 2 336 | 185.7 s |
| C | deterministic | metadata | 16 | 6 | 8 | 8 | 44 | 2 320 | 161.7 s |
| D | hybrid | metadata | **22** | **0** | **14** | **14** | **49** | 2 336 | 184.5 s |

D is the reference for SSR: it ties the best decision quality and false-sufficient
count, and has the highest Recall@40 — hybrid supplies the low-overlap pairs and
metadata ranking lifts `late_evidence` inside the top 40. `late_evidence` still
ends `insufficient`, but now the known pair is selected in both repetitions.
Compatible false-insufficient is unchanged in every arm.

Timing split (sums across two reps):

| Arm | Embedding | Generation | Prioritisation | Jev execution | Wall |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 0 | 239 ms | 0 | 1 103 547 ms | 160.6 s |
| B | 24 709 ms | 276 ms | 0 | 1 106 317 ms | 185.7 s |
| C | 0 | 257 ms | 297 ms | 1 133 817 ms | 161.7 s |
| D | 23 551 ms | 200 ms | 289 ms | 1 097 845 ms | 184.5 s |

The +15 % wall time is embedding computation (~24 s for 500 texts in B/D), not
generation or metadata ranking; both are sub-second. Reusing existing Overgraph
embeddings removes most of that cost. Jev execution dominates the wall time in
all arms.

## B4b full live arms: deterministic vs hybrid generation (2026-10-23)

A deterministic candidate generation and B hybrid (deterministic ∪ embeddings)
ran as full live arms with unchanged ranking, Jev logic and 40-pair budget, two
repetitions each. Artifact: `tests/integration/baselines/b4b-live-arms-v1.json`.

| Measure | A deterministic | B hybrid |
| --- | ---: | ---: |
| Correct / 26 | 16 | **22** |
| False-sufficient | 6 | **0** |
| Coverage complete | 22 | 22 |
| Candidate Recall (known pairs) | 8 | **14** |
| Recall@40 | 6 | **12** |
| Unique conflicts | 4 | 9 |
| Useful facit pairs selected | 3 | 6 |
| Jev calls | 2 320 | 2 336 (+0.7%) |
| Latency | 161 s | 185 s |
| Embedding calls / texts | 0 / 0 | 24 / 500 |

The three synthetic low-overlap contradictions are the direct conversion of
candidate recall into decisions: A returns `sufficient` in all six
case-repetitions; B returns `insufficient` in all six, with both Candidate Recall
and Recall@40 true. `late_evidence` remains `insufficient` in both arms and the
known pair still misses the top 40, so ranking remains the late bottleneck.
Hybrid does **not** fix the compatible-case false-insufficient results.

The pre-registered adoption rule fails only on `jev_calls_not_higher` (2 336 vs
2 320, +0.7%). The artifact therefore says `KEEP_DETERMINISTIC`, even though
hybrid removes six false-sufficient verdicts at essentially the same cost. This
needs an explicit adoption decision rather than a silent criterion change;
ticket 25 records that decision. No production order is changed here.

## B4 candidate generation for low-overlap contradictions (2026-10-23)

B4 isolates candidate generation from ranking: same claims, no budget, no Jev.
Deterministic candidates are compared with embeddings and the hybrid union on
low-overlap contradictions and compatible controls. Artifact:
`tests/integration/baselines/b4-candidate-recall-v1.json`.

| Strategy | Contradiction Candidate Recall | Compatible recall | Mean candidates | Embedding calls / texts |
| --- | ---: | ---: | ---: | ---: |
| Deterministic | 0.25 | 1.00 | 196.3 | 0 / 0 |
| Embeddings | 0.75 | 1.00 | 19.5 | 6 / 59 |
| Hybrid | **1.00** | 1.00 | 196.8 | 6 / 59 |

The deterministic generator misses all three synthetic low-overlap
contradictions (`candidate_miss_synonyms`, semester, notice) while the hybrid
union recovers them in the same candidate volume; embeddings alone miss
`late_evidence`. This is a candidate-generation improvement, not a decision
improvement: B3b showed Jev can still misjudge those pairs, and no Jev call is
made here. B4b must run the full arm with hybrid candidate generation and
measure final decision quality, false-sufficient, coverage and Jev cost before
any adoption. The metadata ranking stays a frozen comparison arm.

## B3c full live arms (2026-10-23)

A (current order) and B (metadata order) ran as full live arms, two repetitions
each, with the A3 contract and 40-pair budget unchanged. Artifact:
`tests/integration/baselines/b3c-live-arms-v1.json`.

| Measure | A current | B metadata |
| --- | ---: | ---: |
| Correct / 22 | 16 | 16 |
| False-sufficient | 2 | 2 |
| False-insufficient | 4 | 4 |
| Coverage complete | 18 | 18 |
| False conflicts | 0 | 0 |
| Jev calls | 2 308 | 2 308 |
| Wall latency | 159 s | 159 s |

Information value per Jev call (separate measurement):

| Outcome | A | B |
| --- | ---: | ---: |
| New relevant contradiction | 4 | **44** |
| New verified compatibility | 81 | 41 |
| Repeated known relation | 85 | 85 |
| Wrong semantic verdict | 0 | 0 |

`late_evidence` was already `insufficient` in both arms, but for different
reasons: A fails closed on incomplete coverage without finding the pair; B
finds 40 contradictions, including the known late pair. The final verdict does
not change because coverage was already blocking. Metadata ordering also makes
`duplicate_contradiction` return CONTRADICTS in both repetitions (the earlier
SCOPE_DIFFERENCE was transient).

The pre-registered non-inferiority criteria all pass, but the stronger
requirement — better final decision quality — is **not** demonstrated. B shifts
calls from compatibility to contradiction detection at the same cost and with
no decision regression; that is useful evidence for a later detection metric,
not a reason to switch the production order. The current order stays.

## B3b staged diagnosis (2026-10-23)

B3b separates three failure stages instead of reporting one recall number:
candidate recall (does the pair exist before budget/ranking?), Recall@Budget
(does it fit the first 40?) and decision correctness (does Jev judge the known
pair correctly, independent of selection?). Artifact:
`tests/integration/baselines/b3b-stages-v1.json`.

| Case | Category | Candidate recall | Rank A/B/C | Jev on facit | Attribution |
| --- | --- | --- | --- | --- | --- |
| duplicate_contradiction | clear | yes | 1 / 1 / 1 | SCOPE_DIFFERENCE (wrong) | jev_wrong_verdict |
| independent_contradiction | clear | yes | 1 / 1 / 1 | CONTRADICTS | none |
| tail_claim_contradiction | clear | yes | 1 / 1 / 30 | CONTRADICTS | none |
| late_evidence | subtle | yes | **1129 / 1 / 1134** | CONTRADICTS | ranking_beyond_budget |
| large_567k | subtle | no facit pair | — | not evaluated | facit_unavailable |
| compatible_periods | compatible | yes | 1 / 1 / 1 | SCOPE_DIFFERENCE (correct) | none |
| compatible_entities | compatible | yes | 1 / 1 / 1 | SCOPE_DIFFERENCE (correct) | none |
| candidate_miss_synonyms | candidate miss | **no** | — | SCOPE_DIFFERENCE (wrong) | candidate_miss |

Recall@Budget over the five contradiction cases with a facit:

| Arm | @1 | @5 | @10 | @20 | @40 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current (A) | 0.60 | 0.60 | 0.60 | 0.60 | 0.60 |
| Metadata (B) | **0.80** | **0.80** | **0.80** | **0.80** | **0.80** |
| Embeddings proxy (C) | 0.40 | 0.40 | 0.40 | 0.40 | 0.60 |

Jev decision accuracy on the evaluated facit pairs: 0.714 (5/7).

**Diagnosis:** `late_evidence` is a **ranking** failure: the pair is generated
but sits at rank 1 129; metadata priority lifts it to rank 1, giving +0.20
Recall@Budget at every budget. `candidate_miss_synonyms` is a **candidate
generation** failure, and Jev also misjudges it, so generation and decision are
both open. `large_567k` has no frozen facit pair, so its stage cannot be
attributed. `duplicate_contradiction` has rank 1 but Jev returned
SCOPE_DIFFERENCE on the direct facit evaluation, so decision correctness needs
live repetition. Embeddings are not dominant: the embedding proxy is worse than
metadata and pushes `tail_claim_contradiction` to rank 30.

No ordering is adopted yet: B3c must run the full live arm with metadata order
and measure final decision quality, coverage and false-sufficient, not just
Recall@Budget.

## B3 pair prioritisation (selection-only, 2026-10-23)

B3 asks whether SWE can choose which fact pairs Jev compares before spending
calls, while keeping the A3 decision contract and the 40-pair budget. The
interface is a pure ranking over the existing candidate universe:
`prioritize_pairs(candidates, claims, ordering=...)`. A later SSR scorer can be
added as another ordering without changing SWE execution.

Arms: **A** current order, **B** deterministic metadata priority (entity,
definition, question overlap, source independence, polarity/value difference,
canonical down-weight) and **C** metadata plus existing embeddings (proxy, not
SSR). Selection makes no model call; Jev still judges.

Artifact: `tests/integration/baselines/b3-selection-v1.json` (no Jev calls).
Recall@Budget on the three pair-gold positive cases:

| Arm | @1 | @5 | @10 | @20 | @40 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current (A) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Metadata (B) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Embeddings proxy (C) | 0.67 | 0.67 | 0.67 | 0.67 | 1.00 |

The known contradictions in pair-gold are already rank 1 under the current
order, so the curve hits its ceiling and cannot show an improvement; the
embedding proxy only pushes `tail_claim_contradiction` down to rank 31. This does
**not** prove that current ordering is optimal for the real gap: `late_evidence`
and `large_567k` have no frozen pair facit. B3b must add verified low-rank
contradiction pairs (especially late/large) and then measure decision quality
and coverage separately before any ordering change. The current order stays.

## B1b hardened gap contract (shadow, 2026-10-23)

B1b is the single pre-registered hardening attempt. The reviewer must choose
anchors from a closed `available_anchors` set (claims in the bounded payload,
selected pairs, coverage reasons, aggregation ids); a real anchor that belongs
to another need no longer supports a gap. Five synthetic cases add two
semantic-gap positives and three clean negatives; they run with scripted Jev so
the only live model is the reviewer. Artifact:
`tests/integration/baselines/b1b-gap-hardening-v1.json`.

Twelve cases are classified (four positives, eight negatives); four neutral
cases (`tail_counterevidence`, `large_567k`, `unknown_counterpart`,
`tail_claim_contradiction`) are explicitly excluded from precision/recall.

| Detector | TP | FP | FN | TN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Narrative B1b | 4 | 6 | 0 | 2 | 0.40 | 1.00 |
| Deterministic metadata | 4 | 5 | 0 | 3 | 0.44 | 1.00 |

| Pre-registered measure | Result |
| --- | ---: |
| Valid report rate | 0.917 |
| Unsupported anchor rate | 0.125 |
| False workflow proposal rate | 0.875 |
| Incremental gap yield | 0 |
| Marginal cost per useful gap | undefined (no incremental gap) |
| LLM / Jev cost | 16 calls, ~46 000 chars, 10.0 s gap latency, 1 170 A3 Jev calls |

Decision: **END_NARRATIVE_BRANCH**. The narrative detector matches the
deterministic recall but has more false positives, proposes workflows on 7/8
negative cases, still produces unsupported anchors, and finds **no** gap the
free deterministic baseline misses. The synthetic clean cases were also
flagged by both detectors because their evidence state stayed
obligation-incomplete, so they do not isolate a coverage-complete semantic gap;
the live pre-registered set is what drives the rejection. B2 is abandoned and
B3 (adaptive pair selection) is the next SWE experiment.

## B1 falsifiable gap hypotheses (shadow, 2026-10-23)

B1 replaces the broad B0 report with four outcomes: `VERIFIED_GAP`,
`SUSPECTED_GAP`, `NO_GAP_FOUND` and `UNDETERMINED`. Every gap names a `need`,
what is missing, motivating observations, an allowlisted workflow and
machine-checkable anchors (`claim:`, `pair:`, `coverage:`, `aggregation:`). The
deterministic validator (`gap_contract.validate_gap_report`) rejects unknown
needs/workflows/anchors and downgrades a broken `VERIFIED_GAP` to
`UNDETERMINED`. A `NO_GAP_FOUND` never claims completeness, and a
`SUSPECTED_GAP` has no execution path.

Artifact: `tests/integration/baselines/b1-gap-hypotheses-v1.json` (one live
run, `gpt-oss-120b`, 11 cases, 11 LLM calls, ~34 400 input characters, ~7.9 s
gap latency, 1 153 A3 Jev calls). Facit: two positives (`late_evidence`,
`missing_source_type`), five negatives (`short_sufficient`,
`compatible_periods`, `compatible_entities`, `duplicate_contradiction`,
`independent_contradiction`); four neutral cases are reported but excluded.

| Detector | TP | FP | FN | TN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Narrative B1 | 2 | 4 | 0 | 1 | 0.33 | 1.00 |
| Deterministic metadata | 2 | 2 | 0 | 3 | 0.50 | 1.00 |

Acceptance:

| Criterion | Result |
| --- | --- |
| `late_evidence` identified | true (SUSPECTED_GAP) |
| `short_sufficient` not VERIFIED_GAP | true (NO_GAP_FOUND) |
| Every VERIFIED_GAP has valid anchors | **false** (2 of 10 invalid: invented `coverage:` anchors) |
| SUSPECTED_GAP triggers no execution | true (no path) |
| A3 verdict unchanged | true |

The narrative detector matches the deterministic baseline on recall but is
worse on precision, and the zero-LLM deterministic detector is better. B1 also
flagged `duplicate_contradiction`/`independent_contradiction` as gaps even
though the contradiction was already found. Before B2 the anchor discipline and
negative gap cases must be hardened, and the narrative must beat the
deterministic baseline rather than repeat its metadata.

## B0 narrative gap review (shadow, 2026-10-23)

B0 instruments a bounded narrative gap review next to the unchanged A3 arm. It
receives needs, aggregation status, selected/omitted pair counts, the five
coverage levels and a bounded sample of extracted claims with an explicit
`omitted_claim_count`; it may only report missing evidence, open questions and
allowlisted workflow suggestions. It has **no decision authority**:
`gap_review` is recorded on the report and never read by route, gate or emit.
The prompt is experiment-only (`narrative_gap.py`) and not production-wired.

Artifact: `tests/integration/baselines/b0-gap-review-v1.json` (one live run,
`gpt-oss-120b`). Ten cases, ten LLM calls, ~3 300 input characters per call,
~0.7 s mean gap-review latency.

| Metric | Result |
| ------ | ------ |
| Expected-gap true positives | 1 / 1 (`late_evidence`) |
| Expected-gap false negatives | 0 |
| False positives | 9 / 9 |
| Cases flagged | 10 / 10 |
| Gap errors / invalid workflows | 0 |

The review flagged every case, including `short_sufficient`, so with the
current broad schema it is over-eager and has no usable precision. That is a
B0 instrumentation result, not evidence for or against Variant B. B1 must
tighten the gap facit and the report contract before the precheck is compared
with A3.

Three metrics stay separate in the B artifact: `contradiction_detection`,
`evidence_coverage` and `decision_correctness`; a coverage-negative decision is
not evidence that Jev misunderstood the material.

## Coverage (five levels)

Coverage is reported per level with an explicit control. The levels are never
collapsed into one percentage: 100 % passage coverage can still miss a
contradiction that candidate generation never proposed.

| Level | Question | Control | `complete` requires |
| ----- | -------- | ------- | ------------------- |
| `ingestion` | Was the whole source material ingested? | provided EvidenceSet | no `found` item with an empty excerpt (upstream ingestion marked `not_measured`) |
| `passage` | Were all relevant passages judged? | character cover | judged chars == source chars |
| `claim` | Were all claim candidates handled? | candidate status | no `unprocessed`; `uncertain` is reported separately |
| `conflict_candidate` | Were mandatory fact pairs proposed and judged? | process (+ facit) | no omitted-by-budget and no unevaluated; with a bound facit also no missing facit pair |
| `narrative` | How much did the narrative model review? | none yet | `not_applicable` before Variant B |

Process levels gate `sufficient`. The conflict level has a process control and,
when a benchmark facit is bound (`bind_pair_facit`, experiment-only), a facit
control as well: a pair that was never generated is invisible to a job counter
and can only fail the facit control. Without a facit the level reports
`not_measured` and only the process control gates. Narrative is
`not_applicable` until Variant B.

The pair-judgement workflow timing in `pair-judgement-v1.json` shows the
distinction: on `tail_claim_contradiction` the facit pair was judged, but
15 717 candidate pairs were omitted by the 40-pair budget, so the conflict
level is `incomplete` (`pair_budget_omitted`) and `coverage_incomplete` blocks
`sufficient`. On the small cases the conflict level is `complete` with facit.
This is deliberately fail-closed: a large underlag cannot claim coverage merely
because every generated job finished.

## Package

`app.services.research.sufficiency_experiment` — not imported by
`build_llm_research_assessor`. Execution is `SufficiencyLoop` →
`WorkflowRunner.run`.
