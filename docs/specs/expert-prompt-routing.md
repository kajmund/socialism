# Expert prompt routing

## Purpose

Expert instructions use three levels so adding a tool does not grow an
always-on system prompt:

1. `workspace.voice.system` contains identity, language, safety, evidence and
   result-handling rules.
2. `workspace.voice.tool.*` owns each tool's capability boundary and contract.
3. `workspace.voice.task.*` contains short multi-tool workflow instructions.
   Text chat includes a task prompt only when Jev scores one of that cluster's
   tools above the relevance floor.

Workspace state remains in `workspace.chat.turn`. It is not sent to Jev's
scoring state, so filenames and document inventory cannot influence semantic
tool retrieval.

## Runtime flow

```text
current message
  -> deterministic state filter
  -> Jev tool scores
  -> exposed and ranked tool schemas
  -> task clusters from relevant scores
  -> expert model
  -> tool result
  -> Jev re-rank of the full workspace catalog
  -> expert continuation
```

Pinned lookup tools may remain exposed below the relevance floor. They do not
activate task context unless Jev fails; on explicit Jev fallback, all exposed
clusters are included so the reduced system prompt does not remove operating
instructions.

After `find_documents`, `search_knowledge`, or `read_source`, the connection
used by the tool has been released before the result is sent to Jev. The
post-result re-rank lets a lookup expose the correct presentation step. In
particular, multiple complete `find_documents` results rank
`show_document_set` without treating its presentation limit as a search limit.

## Prompt ownership

- General safety or result-integrity rule: `workspace.voice.system`
- Current view and selection data: `workspace.chat.turn`
- One tool's inputs, outputs and negative boundary:
  `workspace.voice.tool.<name>`
- Required cooperation between exposed tools:
  `workspace.voice.task.<cluster>`
- Tool argument shape: Pydantic/client JSON schema, not prompt prose

Do not repeat tool-specific modes or argument instructions in the system
prompt.

## Measurement

Frozen results are:

- `backend/tests/integration/baselines/expert-prompt-routing-v1.json`
- `backend/tests/integration/baselines/expert-prompt-routing-v2.json`
- `backend/tests/integration/baselines/expert-find-show-e2e-v1.json`

The six-case gold set covers smalltalk, filename open, document-type search,
active-set filtering, content search and passage highlighting. The live
treatment also executes the two-step
`find_documents -> show_document_set` continuation.

Headline result from the measured run:

- always-on workspace prompt: 7,688 -> 1,470 characters (-80.9%)
- estimated tokens (`chars / 4`): 1,922 -> 368
- first-tool accuracy: 0.8333 -> 1.0
- smalltalk without a tool: 1.0 -> 1.0
- complete find/show chain: 0.0 -> 1.0
- five-sample time to `show_document_set` call: median 1,491.4 ms,
  mean 1,738.3 ms, range 1,188.6–3,041.8 ms
- post-result Jev cost: median 290.4 ms, mean 299.0 ms
- calls per chain: 2 LLM, 2 Jev, 0 embeddings

After `find_documents`, the post-result Jev decision sets the continuation's
`tool_choice` to `required` when its existing `require_tool` threshold is met.
Before that flag was connected, a five-run probe produced the gallery call in only four runs;
one run printed source IDs as text. With the required continuation, all five
runs produced `show_document_set` and preserved the full result separately
from presentation IDs.

Live latency is observational and must not be a CI threshold. CI checks frozen
headlines, active prompt size, task-cluster selection, migration round-trip and
the reroute contract. OverGraph retrieval latency remains covered by its
existing integration baseline. The end-to-end boundary is the backend's
`show_document_set` call; browser transport and DOM rendering are not included.

## Database migration

Migration `180_workspace_prompt_split` inserts the task prompt fields and
updates defaults for the minimal system, turn and affected tool contracts.
Exact unmodified customer overrides migrate with the defaults. Customized
overrides are preserved rather than overwritten.
