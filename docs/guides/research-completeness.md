# Local sufficiency vs global completeness

Two different judgments sit in the research loop. They are not substitutes.

## Local sufficiency (`ResearchAssessment`)

Asks: **do the ResearchNeeds we already know about have enough persisted evidence?**

- Input is the original `research_plan_snapshot` plus the accumulated EvidenceSet.
- `insufficient` derives follow-up needs from named gaps (`origin=derived`).
- A plan can be locally `sufficient` while the original research objective is still unanswered, because a material question was never generated.

## Global completeness (`ResearchCompletenessPass`)

Asks: **relative to the immutable research objective, did the plan omit a material question?**

- Runs only after the local loop is terminal: no pending/runnable need executions **and** the latest local assessment is `sufficient`.
- Input is the persisted objective, the initial plan snapshot, all runtime needs, assessment history, and EvidenceSet summaries/provenance.
- The reviewer does not retrieve. Missing questions are candidates. They go through the same validate / dedupe / budget path as local follow-ups, then the existing async retrieval loop.
- Persisted lineage is explicit: `origin=global_completeness`, `source_completeness_pass`, rationale in `source_gap`. These rows are not local evidence-gap follow-ups.

## Where freeze sits

```text
objective → initial plan → retrieve / assess / follow-up
        → no pending needs + latest local assessment sufficient
        → GLOBAL COMPLETENESS CHECK
              ├─ complete → freeze EvidenceSet, Attempt ready
              └─ incomplete
                   → persist global runtime needs
                   → bounded retrieval
                   → local reassess
                   → global gate again
```

Freeze is allowed only when:

1. the local loop is terminal **and** the latest global pass is `complete`, or
2. a hard budget/stop is reached (`max_iterations`, `max_needs`, `no_novel_followups`, `max_completeness_passes`).

If a budget stop fires while the latest global pass is `incomplete`, research still finishes as `ready` with a frozen EvidenceSet. The incomplete pass and the stop reason stay on the read model. That is a completed research outcome, not a silent success.

Reviewer / model / parse failure is fail-closed: no freeze, Attempt and EvidenceSet `failed`.
