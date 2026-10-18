# Deterministic document presentation experiment

## Decision

The experiment is not approved for production. The deterministic continuation
reduced orchestration latency and external calls, but it did not meet the
required correctness gates.

Production search and presentation remain unchanged.

## Boundary

The experiment adds `presentation: "gallery"` only to a cloned
`find_documents` schema in
`backend/scripts/benchmark_document_presentation.py`. The field is removed
before the production handler runs. Search therefore receives only its
existing `query`, `mode` and limit arguments.

A deterministic `show_document_set` call is accepted only when:

- presentation is exactly `gallery`;
- search completed with `completeness=complete`;
- full and presentation IDs are non-empty unique strings;
- all full IDs belong to the authorized fixture inventory; and
- presentation IDs are a subset of the full result.

Invalid or absent presentation requests use the frozen production
post-result Jev/LLM continuation. No production fallback was added.

## Paired method

Fifty gold cases cover explicit show, count, analysis and ambiguous intent,
plus `replace`, `filter`, `within` and `extend`.

Each case runs initial Jev, the first LLM decision and production
`find_documents` exactly once. Baseline and treatment then receive the same
tool arguments, workspace state and search result. This makes the continuation
comparison paired and guarantees that presentation cannot alter a shared
search result. Separate show/non-show intent pairs test whether the first LLM
still preserves equivalent search semantics.

The first unpaired pilot is retained only under local `backend/data`; it is not
a decision baseline.

## Result

Frozen summary:
`backend/tests/integration/baselines/document-presentation-deterministic-v1.json`.

- Paired arm selections: 50/50 equal.
- Correct treatment document selections: 46/50.
- Equivalent show/non-show intent-pair selections: 21/25.
- Correct treatment presentation decisions: 39/50.
- Incorrect automatic presentations: 10.
- Missed explicit presentations: 1.
- One structured continuation response failed model/schema validation.

Latency and calls:

- Baseline median/P95: 1,711 / 9,510 ms.
- Treatment median/P95: 1,425 / 9,018 ms.
- Reduction: 287 ms median and 492 ms P95.
- Baseline: 100 LLM + 100 Jev calls.
- Treatment: 78 LLM + 78 Jev calls.

The optimization saved 22 LLM and 22 Jev calls, but the acceptance criteria
required 50/50 presentation decisions, 50/50 document selections and no
automatic display for count, analysis or ambiguous intent. It therefore stays
an experiment.

## Regression coverage

`backend/tests/test_benchmark_document_presentation.py` verifies:

- exactly 50 varied cases;
- one shared production search per paired case;
- presentation stripping before search;
- fail-closed server validation;
- 800 full IDs remain intact while 40 presentation IDs are displayed; and
- absent presentation uses the current continuation.

## Step B: observational live channel parity

Step B does not change the failed Step A decision:
`approved_for_step_b` remains false. The live run is explicitly labelled
observational because it may be run despite that gate.

From `backend/`, run the exact 50 gold cases through text, fixed-transcript
one-to-one voice and group voice (150 live `execute_expert_turn` calls):

```bash
uv run python scripts/benchmark_document_channel_parity.py \
  --run-live \
  --output data/document-channel-parity-step-b.json
```

Both flags are required and existing output is not overwritten. Fixed
transcript uses each gold case message directly; the harness does not invoke
STT or TTS. It seeds an isolated SQLite/OverGraph fixture, uses a fresh expert
history for every channel-case, exercises the production lease/fence lifecycle
and delivers presentation calls through each channel's production adapter.
External/model failures are recorded per case without retry so the matrix can
finish. CI only runs mocked harness contracts and never executes the live
matrix.
