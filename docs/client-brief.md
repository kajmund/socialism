# Client brief — Opinionssimulator

## Product

**Opinionssimulator** is an internal tool for testing political messaging against populations of AI agents (personas) grounded in local civic context.

Pilot: Norrköping, 2026.

## What users do

1. Choose or build a **population** (demographic mix of agents)
2. Inspect / compose **personas** (biography, rhetorical style, local knowledge)
3. Write **budskap A / B** (two formulations of the same message)
4. Configure a **scenario** (time window, optional news disruption)
5. Run a simulation and read **results** (engagement, district heatmap, topic drift, opinion leaders)

## Out of scope (Phase 1 UI)

- Live LLM simulation (mock results only)
- Auth / multi-tenant
- Real PDF export

## Source of truth for UI

`frontend/mockup/Socialism.zip` — dual visual system (paper simulator + Devbrains admin).
