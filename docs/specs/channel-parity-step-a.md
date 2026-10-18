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
