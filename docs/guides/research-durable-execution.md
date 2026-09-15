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
