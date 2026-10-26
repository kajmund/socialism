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

## Reuse-vs-new audit

Per the root reuse-before-new rule, every concern maps to an existing
counterpart before anything new is proposed. Inventory of the production
research services (`backend/app/services/research/`):

| Concern | Existing counterpart | Decision | Justification |
|---|---|---|---|
| Answer identity + actuality | `result_store.py` (`load_saved_answer`, `_answer_is_usable` with `frozen`/`now`) | **Reuse/extend** | Identity and actuality already live in answer lookup |
| Versioning (`answer_version`) | `run_results.py` attempt/variant history, `_saved_answer_parts` | **Extend** | Add a version number to the existing saved-answer parts; no new table pair |
| Preliminary / finalized | `answer_review.complete_research_freeze`, `KnowledgeAnswerReview` (DB) | **Extend** | Add a preliminary state to the existing freeze/review flow if it is missing |
| Provenance | `answer_graph.py` (`publish_answer`, `_current_basis`, `_rebind`) + Overgraph | **Reuse** | The graph already owns derivation |
| Consumed-input dependencies | `_saved_answer_supported`, research context/basis records | **Extend** | Record consumed answer versions on the existing basis record |
| Invalidation / selective rerun | `question_reuse.py`, `graph_reuse.py`, `reuse_gate.py` | **Extend** | Add stale-marking in the existing reuse gate |
| Evidence strength | `quality_persist.py` (`persist_evidence_quality_drafts`, `ResearchEvidenceQuality`) | **Reuse** | Already exists; kept separate from actuality, as the strategy requires |
| New `answers` table + `answer_inputs` join table | — | **Rejected** | Would be a parallel model; the rows above cover the needs |

The earlier draft's `answers` + `answer_inputs` tables are therefore withdrawn.

## Revised minimal model (extensions, not new models)

```text
saved answer (existing result_store/answer_graph record)
  + answer_version            # extend: monotonic per question
  + completion                # extend: preliminary | finalized (freeze flow)
  + consumed_input_versions   # extend: basis record gains {question_id -> version}

Propagation:
  run.preciseness = preliminary if ANY consumed input answer is preliminary
                  = finalized  if ALL are finalized

Invalidation (extend reuse_gate):
  superseding an answer marks runs that consumed that (question, version)
  stale -> selective rerun through the existing reuse/rebind paths.
```

## Where it lives

- **Not in the SWE kernel.** Like the gym driver, this is a runtime-adapter
  concern: `backend/app/services/research` wraps kernel runs and stamps the
  extensions above.
- **No new tables.** The extensions land on the existing saved-answer/basis
  records (SQLAlchemy models behind `RunStore`/the research DB path; SQLite
  for tests as today). Overgraph keeps provenance as it already does.
- **Proof of the reused path:** each delivery step ships with an integration
  test that invokes the *existing* primitive (e.g. `load_saved_answer` with a
  versioned basis) before the extension is accepted.

## Guardrails

1. Preliminary answers may feed only **read-only** research steps; any external,
   irreversible action requires an explicit commit policy (strategy, risk list).
2. Supersession never deletes: both evidence chains are kept and conflicts are
   marked, not silently overwritten.
3. Reruns are selective and logged: same definition sha + same input versions
   may reuse the cached result (existing DecisionCache semantics).

## Delivery order

1. Extend the saved-answer record with `answer_version` + preliminary state
   (reusing `result_store`/`answer_review`), with tests over the existing lookup.
2. Record consumed input versions on the basis record; propagate preliminaryness
   through run inputs.
3. Extend `reuse_gate` with stale-marking → selective rerun, with a replay test
   proving downstream runs observe the new version and nothing else changes.

## Decision points

- Answer identity key: `(question_id, answer_version)` vs content-addressed?
- Store evidence strength as a scalar now or as structured evaluator output?
- Rerun trigger: automatic on supersession vs explicit operator action first?
