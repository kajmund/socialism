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
- **Auth:** static admin/user login in the SPA (phase 1). **Later:** Supabase Auth (email)
- **Hosting:** Railway (backend service + frontend service)
- **LLM:** DeepSeek via OpenAI-compatible SDK
- **Embeddings (SSR):** OpenAI `text-embedding-3-large` (separate `OPENAI_API_KEY`)

Stack is locked unless explicitly changed. Phase 1 deliberately uses SQLite before Supabase — don't reintroduce Postgres/Auth/LLM deps until that phase.

## Repo layout

```text
socialism/
├── AGENTS.md           # this file
├── README.md
├── .github/workflows/  # CI (pytest, frontend checks, OKF validate)
├── okf.project.yaml    # OKF project (end-user manuals → MCP later)
├── data/               # local corpus + download script (payloads gitignored)
├── docs/               # developer specs, briefs, setup, architecture
├── integrations/       # MCP servers + shared OKF helpers
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
- **Snabbrapport layout or metrics** → update the operator guide `knowledge/manual/lasa-simuleringsrapport.md` (and `knowledge/manual/log.md` when the change is user-visible).
- **Setup, API, architecture, env, troubleshooting for builders** → `docs/` (and service `AGENTS.md` files).
- Do not duplicate the same guide in both places.
- Reuse existing manual tags: `korningar`, `personas`, `populationer`, `budskap`, `grunddata`, `jobb`, `rapporter`.
- Reserved OKF files: `index.md` (listing; root may have only `okf_version` frontmatter), `log.md` (changelog). Concept guides need YAML frontmatter with non-empty `type`.
- Validate before merging manual changes: `make knowledge-validate`.

OKF MCP (later): `npx -y @mfdaves/okf-mcp@0.3.3 --project ./okf.project.yaml mcp`.

## Frontend visual system

- **Visual source of truth:** [`frontend/mockup/extracted/`](frontend/mockup/extracted/) (HTML/CSS/JSX mockup + Devbrains tokens under `_ds/`). Match that look and density for **all admin pages and reports** — do not invent a parallel visual language.
- **Admin surfaces** (Personas, Populationer, Körningar, Jobs, Tools, …): Devbrains charcoal + gold — Tailwind tokens in `frontend/src/index.css` + shadcn, aligned with the mockup. Dense run-config chrome lives in `frontend/src/styles/admin-runs.css`.
- **Reports** (HTML under `/reports/:id` and backend-generated `report.html`): same visual system as the mockup/admin chrome (typography, charcoal/gold, spacing, hierarchy) — not a generic document stylesheet.
- **Admin scrolling:** nothing may scroll under the top nav. See [frontend/AGENTS.md](frontend/AGENTS.md) → **Admin shell / scrolling** (`admin-page` / `admin-page-body`). Do not reintroduce sticky/fixed topnav over page content.

## Frontend i18n (mandatory)

**When changing or updating the GUI, always use the i18n system.** Do not hardcode user-facing strings (labels, headings, buttons, placeholders, toasts, empty states, aria-labels, error copy, etc.) in components.

- Add/update keys in `frontend/src/i18n/messages/sv.ts` and the matching keys in `en.ts`.
- Render via `useLocale()` → `t("section.key")` (and `intl` for dates/numbers).
- Full workflow and exceptions: `frontend/AGENTS.md` → section **i18n / L10n**.

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

**LLM prompts live in the database**, not in application code. Runtime prompt text comes from the active configuration (`prompts` map). See [backend/AGENTS.md](backend/AGENTS.md) → **Prompts (database, not code)**.

## No fallbacks

**Do not implement fallback paths** — not in config, not in LLM/model selection, not in external APIs, not in simulation engines. Fallbacks make behavior non-deterministic: the same input can produce different output depending on what failed silently upstream.

- One configured path per concern. If it fails, **fail loudly** with a clear error — do not try an alternate model, provider, heuristic, stub, or degraded mode unless the user explicitly asked for that alternate.
- Do not suggest "if X fails, try Y" in code, scripts, or docs for this repo unless the user requested Y.
- Tests may mock boundaries; production and benchmark code must not mask missing config or API errors with substitutes.

## CI

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on every pull request and on every push to `main` (including merges). Jobs: backend `pytest` (no smoke), frontend oxlint + vitest, and `make knowledge-validate`. The required status check is named **CI**. Do not merge a PR while it is red or pending. Setup and the merge-gate ruleset: [docs/guides/ci.md](docs/guides/ci.md). Local: `make test`.

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
