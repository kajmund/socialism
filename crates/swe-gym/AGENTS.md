# swe-gym — experiment governance

This directory is a standalone experiment (Sweycoins, budgeted speculation,
self-learning budget allocation). It is not production code, and nothing under
`backend/app` may ever import it.

**Precedence:** within this directory, this file overrides the repository root
`AGENTS.md`. Root rules that conflict with the freedoms below are suspended here.

## Freedoms (suspended root policies)

- Workflow-first execution policy: speculative parallel branches are the point
  of the experiment. Deterministic-first is a baseline arm, not a constraint.
- "No fallbacks" applies to production behavior; comparing alternative paths
  is the experiment itself.
- Reuse-before-new: explore freely. Reuse existing primitives when cheap
  (swe-native, experiments/overgraph_ingest tooling), but new ideas do not
  need a reuse matrix to proceed.
- Frontend, i18n, knowledge/manual, Trello, Supabase and product-auth rules
  do not apply here.

## Non-negotiables (the experiment's own quality requirements)

These are not inherited root rules; they are what makes the experiment's
results worth believing. Violating one invalidates the experiment.

1. Honest measurement: scripted/mocked benchmarks are never presented as live
   model results. Every score states its data, model, seed and cost.
2. Hard cost caps: no branch or run exceeds its Sweycoin/real budget; retries
   and resume charge exactly once (idempotency).
3. Facit isolation: golden answers live outside any strategy's reach; final
   evaluation uses held-out questions only.
4. Reproducibility: policy version, training-data version, seeds, tariffs and
   full run logs are recorded for every result.
5. No irreversible side effects from preliminary results (read-only research).
6. Import direction: nothing under `backend/app` may import this directory.

## Exit criteria

The experiment is killed, extracted to its own repository, or promoted only by
an explicit decision — triggered by (a) the first A/B benchmark result, or
(b) evidence that the gym needs generic SWE-core changes.
