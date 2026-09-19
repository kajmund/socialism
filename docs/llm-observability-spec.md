# LLM observability and searchable logging

Status: implementation specification  
Target: local alpha runtime with the Fly-hosted ELK stack  
Owner: backend

## Decision

The application sends structured events to **Logstash**. Logstash writes them to
**Elasticsearch**. Kibana reads Elasticsearch and is the search, dashboard, and
investigation UI. The local Elasticsearch proxy started by `make start` is for
reading/searching the cluster; it is not the log shipping path.

Every real outbound model attempt must produce searchable structured events,
including successes, provider failures, timeouts, cancellations, application
retries, and rejected structured responses. Feature code must not implement its
own attempt logging.

The first implementation is operational observability, not a legally complete
audit log. Local file logging is the durable diagnostic copy for the running
machine. The existing bounded Logstash queue remains non-blocking and may drop
remote events under sustained failure; every drop must be explicit locally. A
disk-backed delivery spool is a later requirement if Elasticsearch completeness
becomes mandatory.

## Current state and gaps

- `backend/app/logging.py` forwards logs over authenticated HTTPS to Logstash.
- The remote handler currently serializes only a fixed set of fields. Structured
  `LogRecord` extras are discarded, so Kibana mainly receives a message string.
- `backend/app/llm/__init__.py` centralizes most chat calls and already records
  aggregate token/timing data for selected Word-review jobs, but it records only
  successful calls and only when a context-specific recorder is bound.
- Structured-output retries and persona-anecdote retries are application-owned
  and must appear as separate attempts.
- Vision, SSR embeddings, knowledge embeddings, Mem0, and CAMEL/OASIS use other
  client paths and are not covered by the shared chat usage recorder.
- No general request/correlation context is bound to log records today.
- OpenAI-compatible SDKs may retry HTTP requests internally. Hidden SDK retries
  make an "attempt" count inaccurate and must be disabled or instrumented.

## Scope

The following outbound model work is in scope:

1. Chat completions: structured, text, streaming, and tool-calling calls.
2. Vision completions.
3. OpenAI embedding requests, including SSR and knowledge ingestion/search.
4. CAMEL/OASIS model calls used by simulations.
5. Mem0 model and embedding calls.
6. Any new model provider added later.

HTTP calls to ordinary research/data providers are not LLM attempts. They should
use the same correlation context but a separate `external.attempt.*` event family.

## Event model

Each physical provider attempt emits:

1. `llm.attempt.started` immediately before the outbound call.
2. Exactly one terminal `llm.attempt.finished` event in `finally`/exception-safe
   code after success, failure, timeout, or cancellation.
3. `llm.response.rejected` when the provider returned a response but application
   validation rejected it, for example invalid JSON, schema failure, empty text,
   or `finish_reason=length`.

An application retry creates a new `llm.attempt_id`, increments
`llm.attempt_number`, and keeps the same `llm.operation_id`. There is no retry
event without a corresponding new attempt.

### Required fields

| Field | Type | Meaning |
| --- | --- | --- |
| `@timestamp` | date | Event time in UTC |
| `event.name` | keyword | One of the event names above |
| `event.dataset` | keyword | `socialism.llm` |
| `event.outcome` | keyword | `unknown`, `success`, `failure`, `timeout`, or `cancelled` |
| `event.duration_ms` | double | Terminal-event duration |
| `service.name` | keyword | Normally `socialism-backend` |
| `service.environment` | keyword | Normally `local` |
| `llm.attempt_id` | keyword | Unique physical provider attempt |
| `llm.operation_id` | keyword | Stable logical operation across retries |
| `llm.attempt_number` | integer | One-based application attempt number |
| `llm.operation` | keyword | Stable purpose, e.g. `word_review.expert_comment` |
| `llm.kind` | keyword | `chat`, `vision`, `embedding`, or `simulation` |
| `llm.interface` | keyword | `structured`, `text`, `stream`, `tools`, or `embedding` |
| `llm.provider` | keyword | `cerebras`, `deepseek`, or `openai` |
| `llm.model` | keyword | Exact configured model |
| `llm.reasoning_effort` | keyword | Configured effort or null |
| `llm.prompt_tokens` | long | Provider-reported input tokens, when present |
| `llm.completion_tokens` | long | Provider-reported output tokens, when present |
| `llm.total_tokens` | long | Sum when token counts are present |
| `llm.finish_reason` | keyword | Provider finish reason, when present |
| `llm.response_id` | keyword | Provider response ID, when present |
| `llm.schema_name` | keyword | Pydantic response model for structured calls |
| `llm.tool_names` | keyword[] | Tool names made available to the model |
| `llm.message_count` | integer | Number of submitted messages |
| `llm.input_chars` | long | Total submitted text size |
| `llm.input_sha256` | keyword | Deterministic hash of canonicalized input |
| `llm.output_chars` | long | Returned text size, when applicable |
| `llm.output_sha256` | keyword | Deterministic hash of returned text |
| `error.type` | keyword | Exception class or normalized failure category |
| `error.message` | text | Sanitized bounded message |
| `error.stack_trace` | text | Stack trace for unexpected failures only |
| `trace.id` | keyword | Correlates a request, WebSocket turn, or background execution |
| `transaction.id` | keyword | Individual HTTP request/WS turn/job execution |
| `customer.id` | keyword | Customer/tenant ID when known |
| `user.id` | keyword | Actor ID when known |
| `job.id` | keyword | Background job ID when known |
| `run.id` | keyword | Simulation/run ID when known |
| `attempt.id` | keyword | Domain research/run attempt ID when known; distinct from `llm.attempt_id` |
| `document.id` | keyword | Underlag/document ID when known |
| `expert.id` | keyword | Expert/persona ID when known |

Do not calculate monetary cost in the request path. Store token counts and enrich
cost later from a versioned pricing table.

### Example terminal event

```json
{
  "@timestamp": "2026-09-19T22:00:00.000Z",
  "event": {
    "name": "llm.attempt.finished",
    "dataset": "socialism.llm",
    "outcome": "success",
    "duration_ms": 842.4
  },
  "service": {"name": "socialism-backend", "environment": "local"},
  "llm": {
    "attempt_id": "01K...",
    "operation_id": "01K...",
    "attempt_number": 1,
    "operation": "word_review.expert_comment",
    "kind": "chat",
    "interface": "structured",
    "provider": "cerebras",
    "model": "gpt-oss-120b",
    "schema_name": "WordExpertComment",
    "prompt_tokens": 1584,
    "completion_tokens": 219,
    "total_tokens": 1803,
    "finish_reason": "stop",
    "message_count": 4,
    "input_chars": 9210,
    "input_sha256": "...",
    "output_chars": 1112,
    "output_sha256": "..."
  },
  "trace": {"id": "..."},
  "job": {"id": "..."},
  "customer": {"id": "..."}
}
```

## Content and privacy policy

Do not send raw prompts, responses, document text, chat messages, memory contents,
tool arguments/results, authorization headers, API keys, cookies, email addresses,
or uploaded filenames to ELK in phase 1.

Log metadata, IDs, sizes, schemas, tool names, token usage, and SHA-256 hashes.
Hashes allow repeated-input/output detection without making customer content
searchable. Error messages must pass a central sanitizer and be capped; known SDK
errors should be represented by type, status code, provider request ID, and safe
message rather than serialized request/response bodies.

If content inspection is later required, design a separate access-controlled trace
store with explicit retention and customer scoping. Do not add an ad-hoc
`LOG_PROMPTS=true` switch to general application logs.

## Backend design

### 1. Preserve structured fields in the logging pipeline

Extend `LogstashHTTPHandler` to serialize one allowlisted structured payload from
the record instead of accepting arbitrary `LogRecord.__dict__` values. Application
code emits through a small helper, for example:

```python
log_event(logger, "llm.attempt.finished", event_data={...})
```

The same JSON representation must be written to the rotating local log. Do not
maintain separate local and remote schemas. Never overwrite Python logging's
reserved fields.

The serializer must recursively accept only JSON scalar/list/object values, cap
large strings, and redact secret-looking keys before either handler sees them.

### 2. Bind correlation context

Add a `ContextVar`-based context module with bind/reset context managers. Context
must propagate naturally through asyncio tasks and be attached by `log_event`.

- HTTP middleware creates or validates `trace.id` and `transaction.id`.
- WebSocket code creates one transaction per inbound user turn.
- Job workers bind job/domain IDs before calling feature code.
- Authenticated endpoints bind `customer.id` and `user.id` after identity is known.
- Feature services bind document, expert, run, and domain-attempt IDs where known.

Do not require every low-level function to pass these IDs manually.

### 3. Add one provider-attempt primitive

Create an exception-safe async attempt primitive used by every provider adapter.
It owns IDs, timestamps, input/output metadata, token extraction, status mapping,
and start/terminal events. It must re-raise the original exception unchanged.
Logging failure must not change the LLM result.

All public chat helpers require a keyword-only stable `operation` value. Making it
required is intentional: type/test failures expose unclassified call sites. The
primitive may accept an existing `operation_id` and `attempt_number` from an
application retry context.

Retain `LLMCallStats` temporarily for job aggregates, but derive it from the same
terminal attempt object so aggregate counters cannot disagree with ELK events.

### 4. Make physical attempts observable

Set provider SDK automatic retries to zero for application-owned clients. The
current OpenAI-compatible client defaults must not create invisible HTTP retries.
Retries that the product wants must be explicit, bounded, and go through the
attempt primitive.

For CAMEL/OASIS and Mem0, inspect the pinned dependency APIs and configure their
model clients with retries disabled. Add adapter hooks at their actual outbound
model boundary. Logging merely around an entire simulation or `memory.add()` is
not sufficient because one operation can perform multiple provider attempts.
Fail the observability test if a dependency upgrade bypasses the hook.

### 5. Cover all adapters

Implement in this order:

1. Shared chat helpers in `app.llm`.
2. Vision.
3. Both embedding implementations; consolidate their attempt instrumentation,
   not necessarily their cache/storage responsibilities.
4. CAMEL/OASIS.
5. Mem0.

Mocks/injected test completers are not provider attempts and must not emit normal
production attempt events. Tests for the observability layer use a fake provider
transport through the real adapter path.

## Logstash and Elasticsearch

1. Route `event.dataset == "socialism.llm"` into the same managed log family with
   an explicit index template before sending the first event.
2. Map IDs, names, provider/model, outcome, and hashes as `keyword`; durations as
   `double`; counts as `long`/`integer`; messages/stacks as `text`; timestamp as
   `date`. Do not rely on dynamic mapping for the `llm.*` namespace.
3. Keep one schema shape. Existing scalar `service` and `environment` fields must
   be migrated to `service.name` and `service.environment` only with a new index
   generation/template, otherwise Elasticsearch mapping conflicts are likely.
4. Apply a 14-day retention policy for alpha LLM operational logs. Revisit after
   measuring volume, especially OASIS simulations.
5. Reject documents with unexpected root fields at the Logstash boundary and log
   the rejection locally without including the rejected payload.

The exact Fly Logstash pipeline and current index names must be inspected before
changing routing. Do not infer them from Kibana's current data view.

## Kibana deliverables

Create a data view covering the new index generation and save:

### Dashboard: `Socialism – LLM operations`

- Attempts over time split by `event.outcome`.
- Failure and timeout rate by `llm.operation`.
- p50/p95/p99 `event.duration_ms` by operation and model.
- Prompt/completion/total tokens by operation and model.
- Application retries: count where `llm.attempt_number > 1`.
- Rejected responses by `error.type`, schema, and model.
- Top slow attempts with trace, job, run, document, and expert IDs.
- Unmatched starts with no terminal event after five minutes.

### Saved searches

```text
event.dataset: "socialism.llm"
event.name: "llm.attempt.finished" and event.outcome: ("failure" or "timeout")
event.name: "llm.response.rejected"
llm.attempt_number > 1
trace.id: "<id>"
job.id: "<id>"
run.id: "<id>"
```

## Tests and acceptance criteria

### Unit tests

- Structured payload survives both local and Logstash serialization unchanged.
- Reserved logging fields cannot be overwritten.
- Secret-key redaction and string-size limits apply recursively.
- Success, timeout, cancellation, SDK error, empty response, invalid JSON, schema
  rejection, and `finish_reason=length` produce the required event sequence.
- Two structured attempts share one operation ID, have distinct attempt IDs, and
  use attempt numbers 1 and 2.
- Streaming emits a terminal event even when iteration raises midway.
- Embedding batches emit one attempt per outbound batch, not per input string.
- Correlation context is isolated between concurrent asyncio tasks.
- Logging never changes or swallows the provider exception.

### Coverage guard

Add a test/architecture check that enumerates allowed provider-client construction
and outbound call sites. Direct `AsyncOpenAI(...)`, `chat.completions.create`, or
`embeddings.create` outside approved adapter modules fails the test. Include the
CAMEL/OASIS and Mem0 integration seams in the allowlist with explanatory comments.

### Integration acceptance

1. Run one successful chat, one forced structured retry, one embedding batch, one
   provider error, and one cancelled stream.
2. Confirm every physical attempt in the fake/provider counter has one start and
   one terminal event in Elasticsearch.
3. Confirm rejected structured output has a linked rejection event.
4. Search each case in Kibana by `trace.id` and by its domain ID.
5. Confirm no prompt, output, secret, document text, or email appears in `_source`.
6. Stop Logstash temporarily; verify model requests remain non-blocking and local
   logs explicitly report remote delivery loss.

## Implementation sequence

Keep this out of per-commit CI beyond focused unit/architecture tests. The live
Fly/Kibana verification is manual or nightly.

1. Structured serializer, sanitizer, context binding, and tests.
2. Shared chat attempt primitive and required operation names.
3. Vision and embedding adapters.
4. CAMEL/OASIS and Mem0 adapter hooks.
5. Elasticsearch template/retention and Logstash routing.
6. Kibana data view, searches, and dashboard.
7. Manual end-to-end verification against Fly.

Do not combine this work with the future expert `search_logs` tool. First make the
events complete and consistently structured; then expose a read-only, scoped log
search tool over the stable schema.

## Cursor implementation brief

Implement this specification in small reviewable commits. Start with phases 1–2
and stop after the shared chat path is fully tested. Report:

1. The complete inventory of provider call sites found.
2. The event schema and any deliberate deviations from this document.
3. Tests proving success/failure/retry/cancellation behavior.
4. Remaining uninstrumented paths (vision, embeddings, OASIS, Mem0) with exact
   files and proposed seams.

Do not log raw model content, do not add silent fallbacks, do not add provider SDK
retries, and do not modify the live Fly ELK configuration in the first PR.
