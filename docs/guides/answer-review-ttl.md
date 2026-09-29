# Source-independent answer review TTL

Research enriches knowledge without revalidating historical EvidenceSets. TTL is
an invitation to consider improving an answer, **not** an expiry, invalidation,
or legal `valid_to` date. More knowledge can nuance an earlier answer.

## Common research boundary

All providers use the same producer. When the common research loop freezes an
EvidenceSet, it captures one final answer basis per normalized question. This
happens after retrieval, follow-ups, assessment, and any parent-answer synthesis.
The snapshot combines all found evidence linked to that question, including
excerpt-only, reused, domain-interpreted, and derived evidence. Providers do not
choose TTL, enqueue candidates, or know about the review lifecycle.

There is no standalone synthesized-answer entity yet. An answer version is the
customer + question key + module/case scope + the set of cited evidence references.
Evidence identity is source type/id/url, locator and content hash. The final
assessment, interpretations and derived excerpts are LLM wording: they are stored
and sent to the classifier but never part of the version hash, so rediscovering
the same evidence does not mint a new version or reset the review clock.
The snapshot contains source references, content hashes, source excerpts,
interpretations where present, and the question's final sufficiency/gap assessment.
Only the current attempt's needs and evidence are read, using their existing
indexes; historical graph nodes and EvidenceSets are not scanned. Duplicate need
links are consolidated. Unanswered questions without found evidence create no
answer version.

The common freeze transaction inserts `knowledge_answer_reviews` with status
`awaiting_ttl`. The row is durable when research becomes `ready`. **Research makes
no TTL model call and never waits for TTL classification or candidate processing.**

## Jev decision in a separate process

The independent `classify` command asks Jev about the whole captured answer basis,
not one provider's contribution. It sends a bounded overview, including the full
source-type set, total evidence count, final assessment, and compact source detail.
Truncated detail and omitted-item counts are explicit in the request.

| Choice | `review_after` |
| --- | --- |
| `soon` | Answer creation time + 3 calendar months |
| `later` | Answer creation time + 6 calendar months |
| `never` | `NULL`: no scheduled review |

Dates are computed in UTC; month ends clamp (31 January → 30 April). Classification
is deliberately asynchronous, so a new answer briefly has no TTL decision.
`awaiting_ttl` is distinct from an explicit `never`. Time starts at answer creation,
not when a delayed worker finally classifies it. TTL never gates research or reuse.

Classification takes one indexed row at a time with a two-minute durable lease,
commits, and returns the database connection before calling Jev. Success writes the
choice only if the worker still owns the lease token. A crashed/cancelled worker's
lease can be reclaimed. An expired worker cannot overwrite a newer decision.
Every claim counts as an attempt (also a worker crash, whose lease later expires).
Any failure, Jev or otherwise, keeps the row `awaiting_ttl`, stores the error
category and retries with exponential backoff (5 min, 10, 20 … capped at 6 h). After
5 attempts the row is parked (`awaiting_ttl`, no `next_classification_at`) and is
visible with `list --status awaiting_ttl`; a failing row never blocks the rest of
the batch and never becomes `never` by default.

## Operating the separate process

From `backend/`, using the configured trusted database connection:

```sh
uv run python -m app.services.knowledge.answer_review_worker classify --limit 100
uv run python -m app.services.knowledge.answer_review_worker enqueue --limit 100
uv run python -m app.services.knowledge.answer_review_worker list --customer-id 7
uv run python -m app.services.knowledge.answer_review_worker list --customer-id 7 --status awaiting_ttl
uv run python -m app.services.knowledge.answer_review_worker complete --customer-id 7 --id ANSWER_VERSION_ID
```

Each invocation handles at most 1–500 rows (default 100). Run `classify` and
`enqueue` in a separate deployment process/scheduler as appropriate. This PR does
not start a loop in the API/research worker or configure a deployment scheduler.

`enqueue` atomically changes due `scheduled` rows to `candidate`. It uses
`(status, review_after, id)`; classification uses
`(status, next_classification_at, id)`. PostgreSQL materializes each bounded batch
and uses `FOR UPDATE SKIP LOCKED` for concurrent workers. Listing requires a
customer and uses `(customer_id, status, review_after, id)`. No queue step scans
the graph, uses offsets, or loads unrelated answers.

Repeated capture of an identical version never resets its clock or reopens a
completed candidate. Changed knowledge produces a new version. Completing a
candidate acknowledges it; it does not itself run research or alter the answer.
The table is internal, with PostgreSQL RLS and no browser-facing policies.

## Rollout and boundaries

The unreleased migration creates an empty queue; there is no historical
classification/backfill. Existing answers enter the process when the common
research flow completes a new attempt with their evidence.

The former lagen.nu `revalidate_after_events` call and event lookup are removed.
The legacy service/table remain for historical data, without a research caller.
Graph events, explicit claim supersession, frozen snapshots, and existing reuse
freshness rules are preserved.

There are no TTL fields or decisions in lagen.nu passage routing or graph
write-back. Other providers and synthesized answers use the same capture and
classification path. Automatic candidate research, a UI, graph-change triggers,
and learned prioritization remain outside this version.
