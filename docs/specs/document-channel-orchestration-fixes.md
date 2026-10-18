# Document-channel orchestration fixes

## Scope

Targeted corrections for the three defects isolated by the nine-turn
diagnostic. No deterministic presentation fast path and no prompt expansion.

## Fixes

### 1. Continuation call ownership

`_planned_calls` no longer mutates the shared `seen_call_ids` set. It only
filters already delivered or executed IDs and deduplicates within one model
reply. `LibraryToolScope.defer` claims client and initial server IDs;
continuation server IDs are claimed in `_finish_round` before execution.

After `show_document` / `show_document_set` is published, episode
`tool_choice` returns from `required` to `auto` so a later forced round cannot
fail the turn before `finish_workspace_turn` delivers the queued presentation.

### 2. Panel lease transaction boundary

Panel turns create no private `PersonaMessage`. `commit_library_message` still
runs the persist guard (lease renewal) and now commits that write when the row
is `None`, releasing the connection before Jev/LLM/tool work. A one-connection
pool regression proves another client can write immediately afterwards.

### 3. Active-set mode normalization

`normalize_find_mode` keeps content-only follow-ups inside the active document
set: when a set exists and the model requests `mode=replace` without a known
document type, the effective mode becomes `filter`. Explicit
`filter` / `within` / `extend` and category replace stay unchanged. The tool
result reports the effective mode.

## Verification

Nine-turn diagnostic artifact:
`backend/data/document-channel-diagnostic-v3.json`

Frozen summary:
`backend/tests/integration/baselines/document-channel-diagnostic-v2.json`

Result after fixes: 9/9 presentations delivered; Group Voice executes
`find_documents`; content `replace` follow-ups coerce to `filter`.
