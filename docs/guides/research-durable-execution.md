# Durable background research execution

Attempt research is accepted on the HTTP request and executed by an in-process
worker that owns a database lease. The research engine itself is unchanged:
`execute_attempt_research` remains the only loop implementation.

## Claim / lease semantics

`execution_research_claims` is infrastructure, not a second business status.

| Field | Meaning |
| ----- | ------- |
| `attempt_id` | One row per Attempt. Unique. |
| `worker_id` / `lease_token` | Current owner. Empty when unclaimed. |
| `lease_expires_at` | Ownership ends at this timestamp. |
| `start_request` | Objective / plan / context from the start call. |
| `claimed_at` | When the current lease was taken. |

Attempt.status stays the domain truth: `created` → `researching` → `ready` or
`failed`. A claim never says "complete".

Compare-and-set claim:

```text
UPDATE execution_research_claims
SET worker_id, lease_token, lease_expires_at, claimed_at
WHERE attempt_id = ?
  AND (worker_id IS NULL OR lease_expires_at IS NULL OR lease_expires_at <= now)
```

Two workers cannot hold the same active lease. The owner heartbeats
(`research_claim_lease_seconds`, default 60s) by token. Release clears
ownership. A lost heartbeat does **not** mark research complete or failed.
If renew returns false after another worker reclaimed, the old worker
sets a lease-lost fence and cancels its executor so it cannot keep writing.

## Start / idempotency

`POST /execution/attempts/{id}/research`:

- `ready` → **200** with the persisted research read model. No new claim work.
- `created` or `researching` → persist set-once snapshots if supplied, upsert
  the single claim row, **202** with current Attempt state.
- `failed` / `running` / `completed` → **409**. Terminal failed is not re-run.

Repeated starts reuse the same claim. They do not create a second EvidenceSet,
runtime-need inventory, or need-execution rows.

The HTTP handler does not call `execute_attempt_research` and does not keep
the request `AsyncSession` for the worker.

## Worker

1. Open a **new** session from `research_session_factory()` (production:
   `SessionLocal` via the jobs factory; tests inject the in-memory factory).
2. CAS-claim the Attempt.
3. Build router / assessor / planners in that session.
4. Call `execute_attempt_research(..., session_factory=factory)` from
   `app/services/research_worker.py` (outside the LLM-free research package).
5. Heartbeat until the engine returns, then release the lease.

The reclaim loop only **schedules** tracked worker tasks. It does not
await a reclaimed job inline, so scanning other expired claims continues.
Shutdown stops accepting new work and cancels only the poll loop. In-flight
executors keep running; `CancelledError` does not fail-close recoverable
research. Errors while binding assessor / follow-up / completeness (before
`execute_attempt_research`) persist `failed` via `fail_incomplete_research`.

`execute_attempt_research` is the single execution implementation. Direct
calls remain the synchronous test seam.

## Database connections during model work

The initial planner, local assessor, completeness reviewer and follow-up
normalizer run after the current session commits its prepared input checkpoint.
Barrier quality scoring also commits derived evidence before calling the model.
Production sessions use `expire_on_commit=False`, so prepared inputs remain
available without another database read. Result persistence opens the next
transaction; model failures still follow the existing failure/recovery path.
Previously committed evidence is retained and does not imply a completed assessment.

The lagen.nu domain-result cache releases its transaction under the source
session lock, on both hits and misses, before document interpretation. Claims
and edges remain deferred until all documents have been interpreted.

These boundaries return connections to the pool while external work is pending,
leaving capacity for progress reads and lease heartbeats. Pool sizes and timeout
settings are unchanged.

## Recovery

A worker crash leaves Attempt `researching` and the lease to expire. The
reclaim loop (`research_worker_poll_seconds`) or the next start wakes a
worker. Resume:

- reuses `research_objective_snapshot` and `research_plan_snapshot`
- does **not** run the initial `ResearchPlanner` again
- reuses the attached EvidenceSet and existing runtime / need-execution rows
- continues the loop from persisted `research_wave`

Need rows still `running` are retrieved again; evidence item uniqueness
prevents duplicate items. `CancelledError` and lease-lost fencing leave
that work recoverable. Actual engine or pre-loop setup failures still
fail-closed (`created`/`researching` → `failed`, EvidenceSet failed, no
freeze).

Startup no longer marks in-flight research failed.

## Out of scope

WebSocket progress (later spec), distributed schedulers, Graphiti, report
jobs, and explicit cancellation.

## Answer review scheduling

The common freeze/ready boundary records one final answer basis per question,
combining all sources and derived evidence. It only writes `awaiting_ttl` work;
research does not call Jev for TTL or wait for any review process. A separate
bounded classifier chooses `soon`, `later`, or `never`, and an indexed candidate
process promotes due schedules. No provider has TTL logic, and lagen.nu no longer
calls graph-impact revalidation after write-back.
See [answer-review-ttl.md](answer-review-ttl.md) for semantics, retries, and commands.

## Need deadlines

Each ResearchNeed runs under `research_need_timeout_seconds` (default 900).
When that deadline is missed the worker persists one `error` evidence item
(`metadata.reason=need_deadline_exceeded`) and completes the need — the same
path as a source-level provider exception: `evidence_error` then
`need_completed`. The Attempt barrier still fails the Attempt only when a
need execution is actually `failed` (orchestration or worker exceptions).
A timeout cannot leave the Attempt in `researching`, and it does not
fail-close the EvidenceSet. Assessment treats the need as insufficient
(no found evidence) so follow-up or completeness can retry. If persist
already committed before the deadline fires (for example during graph
upsert), the timeout handler writes nothing.

The research view loads the overview and progress events, then applies
websocket frames as they are committed. Each overview refresh also reads
progress events after the sequence already shown, so a missed frame still
updates questions, evidence and status. The overview includes runtime needs
that do not yet have a research question, together with evidence already
committed on their Attempt, while the Attempt is still researching.
