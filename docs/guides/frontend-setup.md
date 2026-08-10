# Frontend setup

Opinionssimulator SPA: Vite + React + TypeScript + Tailwind + shadcn + React Router.

## Init (already done)

The app was scaffolded from the mockup. To recreate from empty:

```bash
cd frontend
pnpm create vite . --template react-ts
pnpm install
pnpm add react-router-dom @supabase/supabase-js
pnpm add -D tailwindcss @tailwindcss/vite
pnpm dlx shadcn@latest init
```

Use **pnpm only** (`pnpm-lock.yaml`). Do not introduce npm/yarn lockfiles.

## Environment

```bash
cd frontend
pnpm install
cp .env.example .env
pnpm dev
```

Required vars (validated in `src/lib/env.ts` — fail fast at boot):

| Variable | Purpose |
| -------- | ------- |
| `VITE_API_BASE_URL` | FastAPI base URL (e.g. `http://localhost:8000`) |
| `VITE_DEV_PROXY` | Set `true` locally so HTTP + WS go through the Vite dev proxy (same origin). Avoids CORS when Vite picks another port (5174, …). Requires backend on `:8000`. Leave unset/false in production builds. |
| `VITE_SUPABASE_URL` | Placeholder for future Auth — required string today |
| `VITE_SUPABASE_ANON_KEY` | Placeholder for future Auth — required string today |

Auth is **not wired** in phase 1: the API client does not attach a bearer token yet. You still need non-empty Supabase placeholders so the SPA boots. Never put `service_role` or database URLs in frontend env.

Start the backend first (see [backend-setup.md](backend-setup.md)).

Open http://localhost:5173/runs.

## Routes

| Path | Page |
| ---- | ---- |
| `/` | Redirects to `/runs` |
| `/runs` | Körningar list |
| `/runs/new`, `/runs/:id/edit` | Configure run (wizard or `?mode=quick`) + results (incl. post-hoc interviews / quality warnings) |
| `/personas`, `/personas/new`, `/personas/:id` | Persona library + composer (library chat, delete/resend, anecdotes) |
| `/populations`, `/populations/new`, `/populations/:id`, `.../edit` | Population list / detail / builder |
| `/messages`, `/messages/new`, `/messages/:id/edit` | Budskapsbibliotek + verkstad |
| `/config` | Grunddata / catalog lists |
| `/jobs` | Background jobs |
| `/reports/:id` | HTML report viewer |

Admin surfaces call FastAPI.

## Check

```bash
pnpm exec tsc -p tsconfig.app.json --noEmit
pnpm lint
```

No frontend unit-test runner by project policy — typecheck + lint + manual browser checks.

## Themes

Admin UI uses Devbrains charcoal + gold (Tailwind tokens in `src/index.css` + dense chrome in `src/styles/admin-runs.css`).

## API client

Use `api.get/post/put/patch/delete` from `@/lib/api` (base URL, JSON, typed `ApiError`). Do not add axios/ky. Domain helpers live under `src/api/`.

Run interview / branch / quality behavior for developers: [runs-interviews-and-quality.md](runs-interviews-and-quality.md). Operator how-tos: [`knowledge/manual/`](../../knowledge/manual/).

## i18n

UI locales live in `src/i18n/` (no i18n framework dependency). Default is Swedish; English is available via the language select in the admin top nav.

| Piece | Path |
| ----- | ---- |
| Provider / hook | `src/i18n/LocaleContext.tsx` → `useLocale()` |
| Catalogs | `src/i18n/messages/sv.ts`, `en.ts` |
| Storage key | `opinionssimulator.locale` |

Smoke-test: switch to English in the admin top nav — `/jobs`, `/runs`, `/populations` (list/detail/`new` builder), `/runs/new`, a run’s **Resultat**-flik, `/personas` (list, card fields, composer, profile modal), `/messages` (list, workshop, variants modal), and `/config` (page + district map) should flip labels; refresh should keep English. New strings: add to `sv.ts` first, mirror in `en.ts`, then call `t("…")`. See `frontend/AGENTS.md`.

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| Blank boot / thrown env error | Missing `VITE_*` vars in `.env` |
| Network / CORS errors | Backend down or `ALLOWED_ORIGINS` mismatch |
| Empty library pages | Backend not seeded (`uv run python -m app.seed`) |
| Jobs never finish | Check `/jobs` and backend logs; simulation engine / DeepSeek |
