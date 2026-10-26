# Living, versioned answers (SWE Sweycoins, phase 2) — design sketch

Status: proposal, not decided. Companion to `docs/SWE_Sweycoins_strategi.md`
section 3.2 and to the measured results in `docs/SWE_Sweycoins_resultat.md`.

## Goal

Answers produced by SWE research runs become *living artifacts*: they can be
published as preliminary, later confirmed or revised, and everything downstream
that consumed them is either inherited from or invalidated by the change.
Three orthogonal properties (from the strategy):

- **Completion degree** (preliminary / finalized) — per run.
- **Actuality** (current / superseded) — per answer, changes when a revision lands.
- **Evidence strength** — measured quality, never folded into actuality.

## Current state

- `backend/app/swe/run_store.py`: `RunStore` protocol with `RunRecord`,
  `InvocationRecord`, `record`, `load_run`, `replay_results`, `events`.
- `backend/app/swe/cache.py`: `DecisionCache` with an exact-key policy — cache
  validity is keyed on inputs, but there is no *versioned answer* concept.
- Overgraph holds knowledge-graph state; the SWE kernel (`swe-native`) is a
  pure in-memory interpreter with no persistence opinions.

What is missing: answer identity, status transitions, a dependency edge between
"this run consumed that answer", and a rerun trigger when a consumed answer
changes.

## Proposed minimal model

```text
Answer {
  question_id
  answer_version            # monotonically increasing per question
  status                    # preliminary | finalized
  actuality                 # current | superseded
  evidence_strength         # evaluator score, never merged into status
  provenance                # run_id + input answer versions + definition sha
}

Run {
  run_id
  input_answer_versions     # {question_id -> answer_version} consumed at run time
  output_answers            # answers this run produced
}

Propagation:
  run.preciseness = preliminary if ANY input answer is preliminary
                  = finalized  if ALL inputs are finalized

Invalidation:
  superseding an answer marks every run that consumed that (question, version)
  stale -> its outputs are re-evaluated and re-run selectively.
```

## Where it lives

- **Not in the SWE kernel.** Like the gym driver, this is a runtime-adapter
  concern: `backend/app/swe` wraps kernel runs, records consumed answer
  versions, and stamps produced answers.
- **RunStore extension** (Postgres via the existing SQLAlchemy path, SQLite for
  tests): `answers` table plus a `answer_inputs` join table. Overgraph keeps the
  knowledge-graph provenance; the answer table owns *answer identity and status*.
  No duplication of the run event log — the ledger of the gym remains the
  experiment's cost record, this is the production answer record.

## Guardrails

1. Preliminary answers may feed only **read-only** research steps; any external,
   irreversible action requires an explicit commit policy (strategy, risk list).
2. Supersession never deletes: both evidence chains are kept and conflicts are
   marked, not silently overwritten.
3. Reruns are selective and logged: same definition sha + same input versions
   may reuse the cached result (existing DecisionCache semantics).

## Delivery order

1. `answers` table + versioning + status/actuality transitions, with tests.
2. Propagation of preliminaryness through run inputs.
3. Invalidation → stale marking → selective rerun, with a replay test proving
   downstream runs observe the new version and nothing else changes.

## Decision points

- Answer identity key: `(question_id, answer_version)` vs content-addressed?
- Store evidence strength as a scalar now or as structured evaluator output?
- Rerun trigger: automatic on supersession vs explicit operator action first?
