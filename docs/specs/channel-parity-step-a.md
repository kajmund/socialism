# Step A: deterministic channel parity

## Scope

This experiment measures document-gallery delivery across expert text, 1:1
voice, and group voice before any live benchmark. It does not change runtime
behavior and does not authorize Step B.

The fixed input is the 50-case `GoldCase` set from
`scripts/document_presentation_benchmark.cases`. Each case supplies one
deterministic expert decision: explicit show requests produce one
`show_document_set`; count, analysis, and ambiguous requests produce none.
The same call is captured through these production adapter seams:

- `app.api.sme_ws._send_workspace_tools`
- `LiveSpeechRuntime._client_tools`
- `GroupVoiceAudioRuntime.emit_workspace_tool`

Transport envelopes are retained until after capture. Normalization then
compares tool sequence, source IDs, mode/state preservation, and duplicate
delivery. Separate stale-callback probes set the 1:1 cancellation signal or
transfer the Group Voice floor before invoking an already-issued client-tool
callback.

## Acceptance

Step A requires 150/150 semantic matches and zero incorrect automatic
displays, wrong selections/modes, duplicates, non-floor presentations, and
late presentations after cancellation. Every presentation must also carry a
turn correlation ID.

Run:

```text
uv run python scripts/benchmark_channel_parity.py \
  --output tests/integration/baselines/channel-parity-step-a-v1.json
uv run pytest tests/test_channel_parity_experiment.py
```

## Frozen v1 result

The semantic target is met, but group presentation has no turn ID and is not
floor-gated. Both 1:1 Voice and Group Voice adapters also emit one late gallery
when an already-issued callback is invoked after cancellation or floor loss.
Because the delivery-safety requirements fail, `approved_for_step_b` is
`false`; Step B must not run.

## Post-fix v2: shared delivery component

The three delivery adapters now share
`app.services.workspace_tool_delivery.WorkspaceToolDelivery`. Each channel
supplies its turn correlation id and a `current` predicate: 1:1 Voice checks
that the turn still owns the socket and was not cancelled; Group Voice checks
that the speaking expert still holds the floor. Text chat passes `request_id`
as the turn id. Every delivery carries `turn_id`, and a stale callback emits
nothing. The group expert reply generates one `request_id` for admission,
delivery and speech, so all three correlate the same turn.

Observed after the change (`tests/integration/baselines/channel-parity-step-a-v2.json`):

- 150/150 semantic matches; zero incorrect automatic displays, wrong
  selections/modes and duplicates.
- 0 missing turn IDs.
- 0 non-floor presentations.
- 0 late deliveries after cancellation or floor loss.
- `approved_for_step_b` is `true`.

Run:

```text
uv run python scripts/benchmark_channel_parity.py \
  --output tests/integration/baselines/channel-parity-step-a-v2.json
uv run pytest tests/test_channel_parity_experiment.py
```

The v1 baseline remains the frozen historical result.
