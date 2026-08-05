# Agent Instructions

This file is the source of truth for any coding agent (Claude Code, Cursor, Codex, etc.) working in this repo. Read it before touching code.

## Product

**Opinionssimulator** — internal tool for testing political messaging against AI agent populations (personas grounded in local context). Swedish UI by default.

## Stack

- **Backend:** Python + FastAPI
- **Frontend:** Vite + React SPA + TypeScript
- **Database (phase 1):** SQLite via SQLAlchemy + `aiosqlite` (local file under `backend/data/`)
- **Database (later):** Supabase Postgres — swap `DATABASE_URL` when ready; keep models/migrations portable
- **Migrations:** SQLAlchemy models + Alembic from the backend
- **Auth (later):** Supabase Auth (not required for phase 1 admin CRUD)
- **Hosting:** Railway (backend service + frontend service)
- **LLM + embeddings:** DeepSeek (OpenAI-compatible SDK; embeddings later)

Stack is locked unless explicitly changed. Phase 1 deliberately uses SQLite before Supabase — don't reintroduce Postgres/Auth/LLM deps until that phase.

## Repo layout

```text
socialism/
├── AGENTS.md           # this file
├── README.md
├── okf.project.yaml    # OKF project (end-user manuals → MCP later)
├── data/               # local corpus + download script (payloads gitignored)
├── docs/               # developer specs, briefs, setup, architecture
├── knowledge/          # OKF bundles (end-user manuals)
│   └── manual/         # Swedish operator guides
├── backend/            # FastAPI service (see backend/AGENTS.md)
└── frontend/           # React SPA (see frontend/AGENTS.md)
```

## Documentation split

Keep audiences separate:

| Location | Audience | Contents |
| -------- | -------- | -------- |
| `docs/` | Developers / agents shipping code | Setup, architecture, engineering notes |
| `knowledge/manual/` | Operators using the Swedish UI | OKF how-to guides (`type: guide`) |

Rules for agents:

- **New user-facing UI flows** → add or update a guide under `knowledge/manual/` (Swedish, no implementation detail) and list it in `knowledge/manual/index.md`.
- **Setup, API, architecture, env, troubleshooting for builders** → `docs/` (and service `AGENTS.md` files).
- Do not duplicate the same guide in both places.
- Reuse existing manual tags: `korningar`, `personas`, `populationer`, `budskap`, `grunddata`, `jobb`, `rapporter`, `simulator`.
- Reserved OKF files: `index.md` (listing; root may have only `okf_version` frontmatter), `log.md` (changelog). Concept guides need YAML frontmatter with non-empty `type`.
- Validate before merging manual changes: `make knowledge-validate`.

OKF MCP (later): `npx -y @mfdaves/okf-mcp@0.3.3 --project ./okf.project.yaml mcp`.

## Frontend visual system (dual)

- **Simulator wizard** (`/simulator`): paper/editorial theme (Lora + Nunito, cream paper) — see `frontend/src/styles/simulator.css`.
- **Admin surfaces** (Personas, Populationer, Körningar): Devbrains charcoal + gold — Tailwind tokens in `frontend/src/index.css` + shadcn.

Do not collapse these into one look unless explicitly asked.

## Dependency policy

**Default: write it yourself. Reach for a library only when the alternative would be non-trivial, error-prone, or reinvention of a standard.** Every dependency is a liability — bundle size, supply-chain risk, future upgrade work.

OK to depend on:

- Things that are genuinely hard to get right (HTTP clients, ASGI servers, SQL drivers, parsers, LLM SDKs, ORM, migrations, auth SDKs).
- The declared stack (FastAPI, React, Vite, Supabase clients, DeepSeek via OpenAI SDK, etc.).

Not OK:

- Helper libraries that wrap 5–20 lines of stdlib or platform APIs.
- Frameworks where a function would do.
- "Nicer API" layers on top of an already-present dependency.

Before adding a runtime dep, answer in the commit message:

1. What exactly does it do that we can't write in <30 lines of clear code?
2. How often does it get used?
3. What's its maintenance / transitive-dep footprint?

Per-stack specifics live in `backend/AGENTS.md` and `frontend/AGENTS.md`.

## Configuration

A single settings module is the source of truth for environment per service (`backend/app/config.py`, `frontend/src/lib/env.ts`). Do not call `os.getenv` / read `process.env` directly in app code. Do not call `load_dotenv` anywhere. If a third-party SDK reads env vars directly, mirror them in the settings module — don't sprinkle `setdefault` elsewhere.

Fail fast on startup if required config is missing. No silent fallbacks that hide real config errors.

## Project tracking (Trello)

When creating or updating tasks for this repo via Trello MCP, **always use this board** (do not invent another):

- **Name:** Socialism
- **URL:** https://trello.com/b/BT9e2tNf/socialism
- **Board ID:** `6a71aeccf10fb662906cfe94`
- **Short link:** `BT9e2tNf`

Set it as the active board (`set_active_board`) before list/card operations if the tool requires a default.

**Every new card must include a description** with:

1. **Vad** — en mening om vad det handlar om
2. **Att göra** — korta punkter om vad som behöver göras

Do not create title-only cards.

## Code style (universal)

- **Small, obvious functions.** A 15-line function with clear names beats a three-class abstraction.
- **No premature abstraction.** Three similar lines is better than a badly-named base class. Extract when there's a third caller, not a hypothetical one.
- **No error handling for cases that can't happen.** Trust internal callers and framework guarantees. Validate only at boundaries: HTTP input, external APIs, DB writes, untrusted parsing.
- **No backwards-compat shims** unless explicitly asked for.
- **No feature flags** added speculatively.
- **Comments:** explain *why* when non-obvious, never *what*. Remove stale TODOs.
- **Keep files focused.** Prefer small modules.
