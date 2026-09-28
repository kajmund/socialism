# Answer review TTL

Research enriches the graph without revalidating historical EvidenceSets. A TTL is
a reminder to consider improving an answer, **not** an expiry, invalidation, or
legal `valid_to` date. Growing knowledge can nuance an answer without making the
earlier answer false.

## First version

The first producer is lagen.nu. Its existing Jev passage-routing request includes
one additional choice, `review_ttl`, based on the question and supplied source
passages. There is no additional Jev call, historical graph traversal, or scan of
frozen evidence. Jev still sees the bounded passage payload; this is a heuristic
about the answer's source basis, not a separate assessment of the final legal
interpretation. Invalid/missing choices are explicit passage-routing failures,
never silently interpreted as `never`.

| Choice | `review_after` |
| --- | --- |
| `soon` | Creation time + 3 calendar months |
| `later` | Creation time + 6 calendar months |
| `never` | `NULL`: no scheduled review |

Dates are computed in UTC. Month-end dates clamp to the last day of the target
month (31 January → 30 April). `never` does not prevent future research or a new
answer version. Jev should consider stability and gaps, not source age alone.

There is no standalone synthesized-answer entity yet. In this version an answer
version is a tenant's normalized question plus the sorted set of grounded claims
from one interpreted source result. `knowledge_answer_reviews` records its stable
hash, question, claim IDs, creation time, TTL, and queue lifecycle. The snapshot of
claim IDs identifies its source basis; it does not duplicate or mutate evidence.
Schedules are written in the same transaction as their claims/ANSWERED_BY links.
An irrelevant or failed interpretation produces no schedule.

Repeated retrieval of the same version does not reset its date, replace its TTL,
or reopen a completed candidate. A changed claim set creates a distinct version.
Different customers always have distinct versions. This v1 can therefore have
several candidates for one question when several sources supplied different
answers. Consolidating them is a future policy decision.

## Separate candidate process

Run from `backend/`, using the configured backend database account:

```sh
uv run python -m app.services.knowledge.answer_review_worker enqueue --limit 100
uv run python -m app.services.knowledge.answer_review_worker list --customer-id 7 --limit 100
uv run python -m app.services.knowledge.answer_review_worker complete --customer-id 7 --id ANSWER_VERSION_ID
```

Each invocation is bounded (1–500 rows, default 100). `enqueue` atomically changes
due rows from `scheduled` to `candidate` and records `candidate_at`. Repeated calls
drain the backlog without offsets, duplicate candidates, or rereading completed
work. The `(status, review_after, id)` index supports the range lookup and ordering.
PostgreSQL uses `FOR UPDATE SKIP LOCKED` to let concurrent invocations take separate
batches. Listing and completion require the owning customer; listing uses the
`(customer_id, status, review_after, id)` index. No step loads the knowledge graph.

Schedule `enqueue` in a separate process through the deployment's scheduler when
operationally desired; this PR does not enable a deployment scheduler or start a
loop inside the API/research worker. The CLI returns JSON for inspection. Marking
a candidate complete acknowledges it; it does not itself launch research, create
a revised answer, or change the underlying claims.

The table is internal: PostgreSQL RLS is enabled without browser-facing policies.
Backend/worker access uses the existing trusted database connection. No new
frontend or HTTP endpoint is introduced.

## Existing data and boundaries

The migration creates an empty queue. It does not ask Jev to classify historical
answers or scan/backfill the graph. Older answers acquire a schedule if they are
subsequently interpreted and grounded through the new producer.

The former `revalidate_after_events` call and event lookup have been removed from
lagen.nu write-back. Existing `evidence_set_revalidations`, the legacy service,
and its tests remain for historical data; they are not called by research. Graph
events, explicit claim supersession, and frozen snapshot history are retained.

TTL never changes claim validity, frozen EvidenceSets, or existing reuse/freshness
policy. Passing `review_after` has no effect on whether an answer can be reused.
Other providers do not produce these TTL schedules yet. Automatic candidate
processing, synthesis/retrieval selection, graph-change triggers, and learned
prioritization are outside this first version.
