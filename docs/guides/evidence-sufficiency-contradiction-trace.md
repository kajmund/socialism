# Evidence sufficiency contradiction trace

Why the two contradiction traps in [the sufficiency experiment](evidence-sufficiency-experiment.md)
still end up `sufficient` under live Jev. This is a measurement of the existing
opt-in path, not a production change. PR #426 stays open and unmerged.

Artifact: `backend/tests/integration/baselines/sufficiency-contradiction-trace-v1.json`
(one live run, full per-passage trace). Two live runs were made on 2026-10-22;
the verdicts reproduced and the signal scores stayed within ±0.03.

Reproduce from `backend/` with `TYPESAFE_API_KEY` and `CEREBRAS_API_KEY`:

```bash
uv run python scripts/trace_evidence_sufficiency.py \
  --out tests/integration/baselines/sufficiency-contradiction-trace-v1.json
```

The trace is opt-in (`include_trace=True` in `run_benchmark` / `measure_live_models`)
and adds no scoring path. It records every evaluated passage with the five NOUL
scores, the route answers, the route state, the obligation states and the gate reasons.

## The five control points

| # | Question | Answer |
| - | -------- | ------ |
| 1 | Did Jev see the contradicting passage? | **Yes.** The sentence was inside the judged passage in all four cases (`signal_present=true`, full text in the trace). It was *sent*; it was not *identified*. |
| 2 | What score did it get? | `contradicts_current_evidence` **0.19–0.26**, against a 0.6 threshold. No passage in any case reached 0.4. |
| 3 | What did aggregation do? | **Nothing was lost.** Aggregation never received a contradiction flag, so `unresolved_conflicts=[]` and all obligations verified. |
| 4 | Why did the quality gate approve? | All three projected obligations (relevance, factual support, completeness) were verified by the support passages. `semantic_complete` is computed from those same obligation rows, so it is not an independent check. |
| 5 | Why was the narrative model never called? | The gate allowed `sufficient`, so `escalate_permitted=false` and the route could not escalate. The Jev route's own `uncertain` outcome was then discarded by `_emit_status`, which emits `sufficient` from the gate alone. |

## Per-case trace

| case | signal passage | contradiction score (run 1 / run 2) | gate | Jev route | narrative | result |
| ---- | -------------- | ------------------------------------ | ---- | --------- | --------- | ------ |
| `tail_counterevidence` | `evidence-0:p53`, 629 chars, signal at the end | 0.19 / 0.22 | allows | `UNCERTAIN` | 0 calls | sufficient ❌ |
| `late_evidence` | `evidence-48:p0`, 1 499 chars, signal at the start | 0.26 / 0.25 | allows | `UNCERTAIN` | 0 calls | sufficient ❌ |
| `large_567k` | `evidence-0:p11`, 615 chars, signal at the end | 0.26 / 0.26 | blocks (`obligations_unverified`) | `ESCALATE_NARRATIVE` | 0 calls (`narrative_unbound`) | insufficient |
| `short_sufficient` | `evidence-0:p0` (support, not a contradiction) | 0.05 / 0.05 | allows | `UNCERTAIN` | 0 calls | sufficient ✅ |

`large_567k` is not caught by contradiction detection. Its 17 `found` items are
filler that does not directly support the question, so relevance and factual
support stay unverified and the gate blocks. The route escalates, but the
benchmark binds no narrative, so the run ends as `uncertain` with zero LLM calls.

## Three independent failure layers

### 1. The contradiction question is asked with no other evidence in view

`app/services/research/sufficiency_experiment/jev_eval.py:71` sends one passage
per call. The state is `need_id`, `question`, `passage_id`, `evidence_id`,
`passage` — no other source is supplied. The question being answered is
([evidence_screen.py:60](../../backend/app/services/research/evidence_screen.py)):

> Does this evidence contradict other supplied facts?
> true: It conflicts with other evidence. false: It is consistent or standalone.

There are no other supplied facts, so the honest answer for a standalone passage
is "consistent or standalone". A tail contradiction can therefore not be
identified by construction, only by accident of surface wording. This is why the
scores sit at 0.2 and why making the wording more explicit does not move them.

The route has the same blind spot one level up. `route_state`
(`route.py:139`) is a summary of obligation states, not evidence. For
`tail_counterevidence`, `late_evidence` and `short_sufficient` the route state
is **byte-identical**, and Jev answers all three identically
(`answerable_now` 0.94, `contradiction` 0.04, `confidence` 0.89). The route
cannot distinguish a false-sufficient trap from the positive control.

### 2. A detected contradiction would be dismissed as a duplicate

`resolve_conflict` (`route.py:175`) addresses a conflict when every
contradicting passage also has `likely_duplicate_or_redundant >= 0.6`. All
obligations share the same contradicting passage set, so one duplicate-flagged
contradiction addresses *every* obligation.

Replaying the live scores with only the signal passage's contradiction score set
to 0.95:

| case | signal `likely_duplicate_or_redundant` | `resolve_conflict` addresses | resulting status |
| ---- | -------------------------------------- | ---------------------------- | ---------------- |
| `tail_counterevidence` (run 1) | 0.57 | nothing | uncertain / insufficient |
| `tail_counterevidence` (run 2) | 0.61 | all three obligations | **sufficient** |
| `late_evidence` | 0.89 | all three obligations | **sufficient** |

So even a perfect contradiction detector would not fix `late_evidence`: the
signal passage is mostly repeated filler, Jev calls it redundant, and the
resolver treats "redundant copy" as "conflict resolved". The `tail` case is
decided by a 0.04 margin around the 0.6 duplicate threshold. This replay is a
counterfactual over measured scores, not a second live run.

### 3. The route's verdict does not decide the result

`map_jev_outcome` (`route.py:29`) turns both `sufficient` and `insufficient`
Jev outcomes into `FINISH`; only `uncertain` can reach `ESCALATE_NARRATIVE`,
and only when the gate already forbids `sufficient`. After `FINISH`, `_emit`
calls `_emit_status` (`loop.py:264`), which returns `sufficient` when
`quality.allows_sufficient and all(row.sufficient ...)` — the route result is
not consulted. In this run Jev's route answered `uncertain` for both traps
(`follow_up_change` 0.11 just over the 0.1 risk ceiling), and the emit step
overrode it.

This is the dependency the architecture question identified: the narrative is
reachable only after Jev or the gates have already concluded that something is
wrong. In the false-certainty case neither has, so it can never run. The
benchmark also never binds a narrative (`narrative=None`), so even the one
escalation (`large_567k`) becomes `narrative_unbound` rather than a model call.

## What this implies for a narrative pre-check

A pre-check that only re-asks Jev over the aggregation summary repeats layer 1
and layer 3. To add real signal it must:

1. run on the would-be-`sufficient` path, independent of any contradiction flag;
2. read actual selected excerpts, not only obligation state (bounded by
   `max_narrative_input_chars`, omissions marked, never silently truncated);
3. be able to downgrade only — never upgrade — and fail closed when unbound or
   failing;
4. be gated by size/source count so `short_sufficient` keeps its cost profile.

Fixing layer 1 alone (cross-evidence contradiction question) is not enough
because of layer 2. Fixing layer 2 alone is not enough because of layer 1.
Neither is production scope: both live in the opt-in experiment package.

Design for the comparative experiment: [evidence-sufficiency-narrative-precheck.md](../architecture/evidence-sufficiency-narrative-precheck.md).

## What was not changed

- No production path, thresholds, prompts or `build_llm_research_assessor` wiring.
- PR #426 untouched: this branch sits on top of it.
- The benchmark artifact and its 0.50 / 0.67 figures are unchanged; the trace is
  an additional artifact, not a new measurement of model quality.

## Limitations

- One synthetic golden set with literal contradiction markers; it measures the
  route's handling of a planted contradiction, not general contradiction recall.
- The route and passage NOUL scores come from one judge (`jev-latest`, resolved
  to `jev-1.13.0` in the v1 artifact); a second judge would be a separate
  measurement.
- `tail`'s duplicate score straddles the threshold between runs (0.57 vs 0.61),
  which is itself evidence that a 0.6 duplicate cut-off is too sharp for this use.
