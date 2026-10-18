# Document-channel diagnostic

## Scope

This diagnostic traces three chained requests once through text, fixed-
transcript 1:1 Voice, and Group Voice:

1. `Visa alla hyresavtal.`
2. `Visa bara dem med automatisk förlängning.`
3. `Lägg till anställningsavtalen.`

The active document set from a completed search is materialized into the next
turn's `WorkspaceState`. Instrumentation records initial Jev exposure, the
initial model call, workspace-tool execution, the search result, post-result
Jev exposure, continuation-model calls, and adapter delivery. It does not
change prompts or runtime decisions.

The complete local trace is
`backend/data/document-channel-diagnostic-v1.json`. A later, unscored
single-case Group Voice probe captured the hidden tool exception in
`backend/data/document-channel-diagnostic-group-probe-v1.json`. The concise
result is frozen in
`backend/tests/integration/baselines/document-channel-diagnostic-v1.json`.

## Finding 1: presentation calls are dropped before the adapters

All six text and 1:1 Voice cases completed `find_documents`.
Post-result Jev exposed `show_document_set` in all six. The continuation model
made four raw `show_document_set` calls in text and six in Voice, but none was
delivered.

The defect is in continuation-call deduplication, before channel delivery:

1. `_planned_calls` receives `work.seen_call_ids` and inserts each newly parsed
   continuation call ID into it.
2. `_finish_round` passes the accepted client call to `publish`.
3. `publish` calls `LibraryToolScope.defer`.
4. `defer` checks the same set, sees the ID inserted in step 1, and discards
   the call as a duplicate.

Consequently `finish_workspace_turn` receives no client call. The text,
1:1 Voice, and Group Voice adapters are not the cause of the missing galleries.

## Finding 2: Group Voice holds a write transaction across external work

Jev exposed `find_documents` in all three Group Voice cases. The initial model
selected it in two. Both failed before the production search handler, then
exhausted four required continuation rounds and produced no reply.

The targeted probe captured `sqlite3.OperationalError: database is locked`
while inserting the `workspace_operations` row. The preceding sequence is:

1. A panel turn intentionally creates no private `PersonaMessage`.
2. `commit_library_message` invokes `persist_guard`.
3. The guard updates the expert-turn lease and starts a write transaction.
4. Because the message row is `None`, the function returns without commit.
5. The transaction and connection remain held across Jev/LLM work.
6. Workspace-tool execution opens another session and cannot write its
   operation row in SQLite.

SQLite makes the failure deterministic, but the retained connection and
transaction are also invalid for PostgreSQL under the repository's mandatory
transaction-boundary rule. The earlier statement “Group Voice never calls
`find_documents`” was therefore too broad: the model tried, but execution
failed before the observed handler boundary.

## Finding 3: structured state exists, but mode is still free-form

Text selected `replace`, `filter`, and `extend` correctly in 3/3 cases.
1:1 Voice selected the filter follow-up as `replace`; that broadened the
selection from four leases to all 20 fixture documents. Its following
`extend` was syntactically correct but operated on the already corrupted set.
Group Voice also proposed `replace` for the filter follow-up before database
execution failed.

Passing the active document set in `WorkspaceState` therefore preserves the
referenced IDs but does not enforce the transition. The model still authors
`mode` independently.

The fixture does not encode “automatisk förlängning” as a reliable semantic
gold subset, so this diagnostic distinguishes scope/mode preservation from
content-retrieval quality. It must not be used to approve that search result.

## Error classification

The prior 150-turn run's 45 errors split into:

- 17 provider `400 wrong_api_format` structured-output failures: text 4,
  1:1 Voice 10, Group Voice 3.
- 28 Group Voice `Expert tool episode produced no reply` failures. The
  diagnostic reproduces their pre-handler database-lock path.

No result row recorded a provider timeout. Log transport timeouts printed by
the benchmark were observability failures, not expert-turn outcomes.

## Decision

Production remains unapproved and unchanged. Correctness work should address,
in order:

1. continuation-call ownership/deduplication;
2. the uncommitted panel-turn lease transaction;
3. structured transition derivation for `filter`, `within`, and `extend`;
4. provider structured-output reliability.

After focused regression tests, rerun deterministic delivery Step A before a
new live parity acceptance run.
