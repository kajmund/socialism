# Research progress events

Persisted `ResearchProgressEvent` rows are an **audit/projection** of Attempt research. Domain tables stay authoritative.

```text
durable state transition
        │  same transaction
        ▼
ResearchProgressEvent  (sequence, type, small payload)
        │  after commit only
        ▼
schedule in-process WebSocket fan-out   ← best-effort, at-least-once
        │  never blocks or fails research
        ▼
GET /execution/attempts/{id}/progress-events?after_sequence=N
```

Live delivery is not the source of truth. A hung or failed socket cannot roll back research; catch-up is the reconnect path. Clients dedupe by event id / sequence. There is no exactly-once bus.

`/ws/research` authenticates, then **subscribes before the persisted replay snapshot**, so a transition committed in that window is delivered live (and may also appear in replay). Clients treat that as at-least-once.

## Why this transport

`main` already has in-process WebSocket hubs (`EventHub` for jobs/reports, room registries for run/panel/Word watch). Research uses the same seam: an attempt-scoped registry + `/ws/research`. No new SSE stack. A background worker can emit without an HTTP request context because append + scheduled publish take a session / in-process hub only.

## Payload rules

Events reference existing IDs (`research_need_id`, `need_execution_id`, `evidence_item_id`, assessment/completeness ids). They do not copy full evidence/documents, prompts, or chain-of-thought. User-visible rationale may appear as a short preview.

## Example stream (one Attempt)

Successful single-need run with an explicit objective + plan:

1. `objective_accepted`
2. `initial_plan_accepted`
3. `research_need_planned`
4. `need_queued`
5. `need_running`
6. `evidence_found` (or `evidence_not_found` / `evidence_error`)
7. `need_completed`
8. `local_assessment_persisted`
9. `global_completeness_persisted`
10. `research_frozen_ready`

A follow-up wave inserts `follow_up_need_derived` + another queued/running/evidence/completed cycle before the next assessment. A global-completeness cycle inserts `global_need_derived` (or `capability_unavailable` when the gap is not executable). Provider/worker failure emits `need_failed` then `research_failed`.
