# Evidence sufficiency measurement protocol

Pre-registered comparison protocol for the opt-in evidence-sufficiency arms.
Machine-readable source of truth:
[measurement-protocol-v1.json](../../backend/tests/integration/baselines/measurement-protocol-v1.json).
Locked 2026-10-23, before any arm comparison. No production change; PR #426
stays open and untouched.

Frozen A0 artifact remains untouched:
`sufficiency-a0-freeze-v1.json` plus its two raw repetitions. It is the
historical and operational reference; the paired comparison uses a **new A0
reference** measured under this protocol.

## Two quality measures

A technical failure must never count as successful contradiction detection.
The A0 freeze showed why: one failed `late_evidence` evaluation accidentally
blocked a false `sufficient` and improved measured accuracy without any better
understanding.

**Semantic quality** is measured on clean runs only. A run is clean when every
required model judgement for that decision completed: no timeout, invalid
answer or budget omission affected it. Technical failures are excluded from
numerator and denominator and reported separately. Metrics: accuracy,
false-sufficient, false-insufficient, confusion, true-positive conflicts,
false contradictions.

**Operational quality** includes all independent live repetitions. Metrics:
raw accuracy, operational success (correct and no technical failure),
technical-failure rate, `sufficient_on_failed_call`, and verdict stability
across repetitions. A `sufficient` verdict may never depend on a failed call.

## Paired runs and live runs

Paired runs isolate decision-logic changes from Jev variance. Each Jev response
is recorded in a cassette keyed by

```
sha256(questions canonical JSON) + sha256(state canonical JSON) + model
```

Arms replay entries in the same strict order. A missing entry is an error, not
a silent call: A1 shares its call set with A0 and can be fully paired; A2/A3
calls without a matching entry run live and are labelled in the arm artifact.
Two independent live repetitions per arm remain mandatory for operational
quality; the paired reference never replaces them.

## Coverage

Two distinct coverage types, reported separately and never collapsed:

- **Execution coverage** — all selected work was handled. Deterministic
  process control; gates `sufficient`.
- **Semantic coverage** — evidence that relevant contradictions were not
  missed. Requires a facit or a verifiable strategy; without a facit it stays
  `not_measured`, never `complete`.

Pair states are also distinct: `not_selected` (candidate ranking excluded it),
`budget_omitted` (candidate did not fit the budget), `unevaluated` (selected for
Jev but not judged). Execution coverage covers the last two; semantic coverage
needs the facit. `max_pairs_per_need` stays 40: the budget is not raised for
green numbers before candidate filtering is proven to keep decisive
contradictions.

## Cost

Reported next to quality for every arm: Jev calls, Jev input characters,
embedding calls, LLM calls, wall latency, Jev latency, cost per detected
contradiction, cost per correct decision. There is no arbitrary hard cap; an
arm does not win on quality without its cost.

## PASS/FAIL

Pre-registered criteria (authoritative list in the JSON):

Semantic:

- A1: quality PASS + route `final_outcome=uncertain` is never `sufficient`.
- A2: a forced 0.95 contradiction stays unresolved at duplicate 0.89.
- A3: `tail_counterevidence`, `late_evidence` and `independent_contradiction`
  are not `sufficient` in clean runs.
- A3: `short_sufficient` stays sufficient; compatible cases produce no false
  contradictions.
- A3: clean false-sufficient rate ≤ clean A0 reference; pair budget stays 40.

Operational:

- `sufficient_on_failed_call == 0` for every arm.
- Technical-failure rate is reported and every failed call is traceable.
- Verdict differences across live reps are explained by a recorded failure.
- No alternate model, retry policy or degraded mode appears.

## Arm order

1. A0 paired reference and live repetitions.
2. A2 (implemented).
3. A3 (implemented; `pair_strategy=deterministic` for the comparison).
4. A1 only after [ticket 13](../..) implementation and tests.
5. Variant B only after the A3 decision.

Arm results are written as `arm-<arm>-<date>.json` next to their cassettes. No
arm result may be used for an architecture decision before all PASS/FAIL
criteria above are computed.
