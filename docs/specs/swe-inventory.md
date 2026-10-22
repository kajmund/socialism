# SWE inventory — research orchestration on current `main`

**Status:** PR 1 of SWD 1.0  
**Scope:** Classify existing code before a generic workflow engine exists. No research domain behaviour is changed in this PR.

## Facit

Research’s current loop is the behavioural source of truth. SWD examples describe *engine* semantics (fork/join, expressions, providers). They do not replace `ResearchNeed`, evidence quality, completeness, freeze, or stop-reason semantics.

Preserved product flow:

`ResearchObjective` → Graph/question reuse → `ResearchPlan` / `ResearchNeed` → parallel need execution → `EvidenceSet` → quality/relevance → assessment → completeness → follow-up waves → freeze / stop reason.

## Reuse (domain stays put)

Do not reimplement these. SWE will call them as Python handlers / decision inputs.

| Area | Location | Why |
| --- | --- | --- |
| Need / plan / evidence types | `backend/app/services/research/models.py`, `plan.py`, `planner.py` | Domain contracts |
| Prompt catalog | `prompt_store.py`, `prompt_catalog.py` | Provider questions are `prompt_key` refs, not inline text |
| Assessment + completeness | `assessment.py`, `completeness.py`, `loop_decision.py` | Sufficiency and stop policy |
| Follow-up / runtime needs | `followup.py` | Wave planning |
| Quality + Jev relevance | `quality.py`, `quality_persist.py`, `evidence_screen.py`, `relevance_judge.py` | Scoring and NOUL |
| Router + providers | `router.py`, `registry.py`, `composition.py` | Source selection; not an LLM router |
| Retrieval / reuse / graph | `need_retrieval.py`, `question_reuse.py`, `graph_reuse.py`, `reuse_gate.py` | Knowledge graph read-through |
| Question identity / freeze grounding | `question_iteration.py`, `question_graph.py` | Stable IDs |
| Startup / main-first | `startup.py` | Plan construction |
| Freeze + answer review | `answer_review.py` | Product freeze |
| Research leases | `research/claims.py`, `research_worker.py` | Postgres CAS ownership until SWE storage exists |
| mem0 | `overgraph/mem0_store.py`, `expertgranskning/memory.py` | Expert memory, not workflow state |
| Knowledge TextUnits | OverGraph knowledge catalog | Link by stable ids; do not copy bodies into tasks |
| Model / expert / tool routing | `llm/selection.py`, `expert_reasoning.py`, `expert_worker_spawn.py` | Later feature adapters |

`EvidenceScreenCache` keying (`model`, question-set version, content hash, normalized question) is the contract to reuse for exact Jev cache. It is in-process, FIFO cap 256, and need-scoped scores do not reuse plan-wide scores.

## Moved into SWE (generic orchestration)

These shapes are engine primitives now. Domain callbacks stay in research.

| Today | Engine shape |
| --- | --- |
| `execute_one_need` (per need; deleted `_run_need_executions` shell) | `map` / `task` with concurrency and timeout |
| `_assert_need_barrier` | `join` (`mode: all`) |
| `finish_research_wave` / wave advance (deleted `run_research_loop`) | `decision` routing back with `max_steps` / `max_depth` |
| `loop_decision.py` | Deterministic decision inputs, not a second loop runtime |
| `_write_fence` + lease-lost cancel | cancellation + deadline |
| `seed_need_executions` CAS claim | `pending → claimed/running` |
| `ProgressTracker` | run-event observability |
| `execute_research_question_dag` | generic wave executor |

## Removed after the verified cutover

The cutover is executed; there is no long-lived dual runner.

- [x] Wave/fan-out/join shell: `loop_control.run_research_loop` and
  `execution._run_need_executions` deleted (delete-PR).
- [x] Differential tests: `tests/test_research_swe/test_parity.py` deleted after
  the parity gate; `test_wiring.py` and the research suites remain regression.
- [x] No leftover “if SWE unavailable, use the old loop” path.
- [ ] Duplicate in-process Jev cache: not applicable yet; research still uses
  the domain Jev path and phase-4 provider decisions are not wired into it.

Do **not** remove `ResearchRouter`, quality, completeness, question reuse, mem0, or the knowledge graph.

## OverGraph — verified vs not claimed

Package: `overgraph==0.17.0`. Socialism production still uses the installed wheel.
Phase 2 adds an in-repo SWE crate (`crates/swe-native`, PyO3 module `swe_native`)
for in-memory execution only. It does not open OverGraph catalogs.

Verified against the installed wheel:

- `OverGraph.open(..., wal_sync_mode="immediate"|"group_commit")` — both accepted. Invalid values raise `ValueError`.
- A catalog is a **directory** (`manifest.current`, `wal_0.wal`, …), not a single file.
- `begin_write_txn()`, `WriteTxn.commit` / `rollback` / `upsert_node` / `upsert_edge`, and `graph_patch()` exist.
- `sync()` / `flush()` exist.
- Socialism production opens knowledge/memory catalogs with **`group_commit` only** (`backend/app/services/overgraph/catalogs.py`). `immediate` is unused.
- `Catalog` does not wrap write transactions; production writes are per-upsert under `threading.RLock`.
- Same-process second `open()` on one directory succeeded.
- A second **process** also opened the same directory while the first handle was still live (`P2_OK`). OverGraph 0.17.0 does **not** provide an exclusive multiprocess writer lock. Socialism’s `TenantLock` (`fcntl.flock`) is a host lock, not an engine guarantee.

SWE v1 must open per-customer-feature catalogs with `wal_sync_mode="immediate"` for crash-durable transitions, use `begin_write_txn` / `graph_patch` for claim + state + event, and keep a single local scheduler/owner per catalog. Do not claim crash isolation across processes until a host lock is added and tested.

## Persistence today (not SWE)

Attempt research durability is Postgres: `execution_research_claims` CAS lease, need-execution rows, evidence set freeze. Jobs `fail_interrupted_jobs` is fail-closed on restart and must not be copied for SWE recovery.

## Tests that pin current research behaviour

Keep these as regression facit for later differential runs: `test_research_execution.py`, `test_research_loop.py`, `test_research_loop_decision.py`, `test_research_assessment.py`, `test_research_completeness.py`, `test_research_need_timeout.py`, `test_research_eager_quality.py`, `test_research_worker.py`, `tests/research_reuse/`.
