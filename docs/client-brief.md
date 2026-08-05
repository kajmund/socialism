# Client brief — Opinionssimulator

## Product

**Opinionssimulator** is an internal tool for testing political messaging against populations of AI agents (personas) grounded in local civic context.

Pilot: Norrköping, 2026.

## What users do

1. Choose or build a **population** (demographic mix of agents)
2. Inspect / compose **personas** (biography, rhetorical style, local knowledge, optional anecdote)
3. Maintain a **budskapsbibliotek** and write formulations for injection
4. Configure a **körning** (timeline ticks, optional A/B or stimulus/control branch, OASIS options)
5. Start a simulation (status-only by default, or optional live OASIS) and read **results** / **HTML reports**
6. Interview personas in the library or post-hoc against a finished run’s feed context

## Phase 1 scope

In scope (shipped or API-backed):

- Admin CRUD for personas, populations, runs, messages, catalog
- Background jobs (population generate, run simulate, report generate)
- Optional OASIS multi-agent simulation (`SIMULATION_ENGINE=oasis`)
- Hybrid HTML reports (not PDF)
- Paper **simulator** demo wizard at `/simulator` (mock UI path)

Out of scope for now:

- Auth / multi-tenant
- Supabase Postgres as primary store (SQLite first)
- Real PDF export

## Source of truth for UI

`frontend/mockup/Socialism.zip` — dual visual system (paper simulator + Devbrains admin).
