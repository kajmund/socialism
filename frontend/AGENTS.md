# Frontend — agent notes

This is the React SPA for **Opinionssimulator**. Read [../AGENTS.md](../AGENTS.md) first — universal building rules live there. This file adds frontend-specific conventions.

## Stack

- **Plain React SPA** (Vite + TypeScript, strict). **Not Next.js** — do not suggest Next, SSR, server components, or file-based routing.
- **Tailwind CSS** for styling. No CSS modules, styled-components, Emotion, or `.module.css` files for component styles. Global theme tokens live in `src/index.css`.
- **Admin theme:** Devbrains charcoal + gold via Tailwind tokens + shadcn. Run list/config styles live in `src/styles/admin-runs.css` (`.theme-admin`).
- **shadcn/ui** for UI primitives (admin surfaces). Add components with `pnpm dlx shadcn@latest add <name>` — don't hand-roll what shadcn already ships.
- **React Router** for routing.
- **`@supabase/supabase-js`** for auth (email only — no Google sign-in, no SSO providers).

## Package manager

**`pnpm` only.** Do not use `npm install` or `yarn add`. The lockfile is `pnpm-lock.yaml`. If you see `package-lock.json` or `yarn.lock` appear, that's a bug — delete it.

**Minimum release age: 7 days.** Configured via `.npmrc` (`minimum-release-age=10080` minutes). pnpm will refuse to install any package version published less than 7 days ago. This defends against typosquat / compromised-release attacks where a malicious version of a popular package goes live and gets pulled within hours.

If a fresh package is genuinely required (e.g. urgent security fix in a dep we already use), override per-install and justify in the commit message — don't lower the global threshold.

## Dependency policy

See universal policy in [../AGENTS.md](../AGENTS.md). Frontend-specific:

- **HTTP:** use the native `fetch` API through a thin client in `src/lib/http.ts` and the `api` singleton in `src/lib/api.ts`. **No axios, ky, got, superagent, redaxios.**
- **Dates:** use native `Date` and `Intl.DateTimeFormat`. No moment, dayjs, date-fns unless genuinely needed.
- **Utilities:** use native `Array` / `Object` / `Map` methods. No lodash, ramda.
- **State:** `useState` / `useReducer` / `useContext` first. Only reach for external state libraries when the pain is real.
- **Forms:** native `<form>` + `FormData` first.
- **Validation:** only add a schema library when we actually need runtime validation at boundaries.
- **UI components:** shadcn primitives via `pnpm dlx shadcn@latest add <name>`. Don't hand-roll what shadcn already ships.

Before adding a package, check:

1. Is there a native browser or TS/JS API that does this?
2. Does shadcn/ui already cover it?
3. Is it small, well-maintained, and worth the maintenance cost?

If yes to (3), add it — but flag the decision in the commit message.

## Layout

```text
frontend/
├── src/
│   ├── components/        # App components. shadcn under components/ui/
│   ├── data/              # Shared types + helpers
│   ├── api/               # Domain API helpers (personas, populations, runs)
│   ├── i18n/              # Locale catalogs + LocaleProvider (sv default, en)
│   ├── lib/               # http, api, auth, supabase, env
│   ├── pages/             # Route-level components
│   ├── styles/            # admin-runs.css (dense run-config chrome)
│   ├── App.tsx            # Router
│   ├── main.tsx
│   └── index.css          # Tailwind + Devbrains tokens
├── mockup/                # Historical HTML mockup (zip + optional extract)
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```

Keep imports consistent with the `@/*` alias (e.g. `@/lib/api`, `@/components/ui/button`).

## i18n / L10n

**Mandatory for all GUI changes.** Any new or updated user-facing UI text must go through i18n — never hardcode Swedish/English strings in components. See also root [../AGENTS.md](../AGENTS.md) → **Frontend i18n (mandatory)**.

Swedish is the default UI locale. Do **not** add `react-i18next` / `lingui` unless catalogs outgrow a small helper.

- Catalogs: `src/i18n/messages/sv.ts` (source of truth for keys) and `en.ts` (same shape).
- Runtime: `LocaleProvider` + `useLocale()` from `@/i18n` (`t(key, params?)`, `locale`, `setLocale`, `intl` for `Intl.*`).
- Persist choice in `localStorage` (`opinionssimulator.locale`); sync `document.documentElement.lang`.
- Language switcher lives in `AdminShell` (admin chrome). Migrated so far: nav, Jobs, Runs list/detail/configure/results, Populations list/detail/builder + job toasts, Personas list/composer/card-fields/profile, Messages list/workshop/variants, Config page/map.

**Adding a string**

1. Add the Swedish copy under the right nest in `messages/sv.ts`.
2. Add the English copy for the same key path in `messages/en.ts` (TypeScript enforces matching keys).
3. Replace hardcoded UI text with `const { t } = useLocale(); t("section.key")` (use `{name}` placeholders for interpolation).
4. For dates/numbers, use `intl` from `useLocale()` with `Intl.DateTimeFormat` / `Intl.NumberFormat` — do not hardcode `"sv-SE"`.

Still hardcoded (next slices): OASIS simulation prompts (intentionally Swedish). Report HTML language follows UI locale at order time (`locale` on `POST /reports`).

## Routes (current)

| Path | Status |
|------|--------|
| `/` | Dashboard (startsida) |
| `/runs` | Körningar list |
| `/runs/new`, `/runs/:id/edit` | Körning (wizard / quick + Resultat) |
| `/jobs` | Bakgrundsjobb (population, simulering, report) |
| `/personas` | Persona library (grid/list) |
| `/personas/new`, `/personas/:id` | Persona-kompositör (+ chat) |
| `/populations` | Population list |
| `/populations/:id` | Population detail |
| `/populations/new`, `/populations/:id/edit` | Population builder |
| `/messages` | Budskapsbibliotek |
| `/messages/new`, `/messages/:id/edit` | Budskapsverkstad |
| `/tools` | Verktyg (flikar: konfigurationer, playground, cache) |
| `/tools/configurations` | Konfigurationer (namn + språk + prompts + SSR-temperatur + grunddata) |
| `/tools/configurations/new`, `/tools/configurations/:id/edit` | Skapa/redigera konfiguration |
| `/tools/playground` | Anchor-/SSR-kalibrering + prompt-iteration |
| `/tools/cache` | Lista/rensa diskcachade SSR-ankarembeddings |
| `/configurations`, `/playground`, `/config` | Redirect → `/tools/...` |
| `/reports/:id` | HTML-rapport |

Home is `/` (dashboard). Unknown routes redirect to `/`.

## Themes

- **Admin theme:** Devbrains charcoal + gold. Dense run-config chrome lives in `src/styles/admin-runs.css` under `.theme-admin`. Use Tailwind + shadcn for new admin chrome where practical.

## Code style (frontend-specific)

- **TypeScript strict.** No `any` unless there's no alternative; prefer `unknown` and narrow.
- **Small, composable functions and components** over clever abstractions. Three similar lines > a premature generic.
- **One component = one file.** Components stay small enough to fit on one screen.
- **Tailwind classes inline** for admin.

## Configuration

- All env reads go through a single `src/lib/env.ts` module that validates required vars at boot. Never read `import.meta.env.X` directly in components.
- Env vars are prefixed `VITE_` (Vite convention). Anything not prefixed is not exposed to the client.

## Backend integration

- Talks to a separate Python backend over JSON. URL comes from `VITE_API_BASE_URL`.
- Always use `api.get/post/put/patch/delete` from `@/lib/api` — it handles base URL, JSON, Supabase bearer token, timeouts, and typed `ApiError`s (including the `isNetworkError` flag that distinguishes CORS/network from HTTP errors).
- Auth is Supabase email. The bearer token is injected automatically via the `api` client; never thread tokens through component props.
- Admin surfaces (personas / populations / runs) talk to the FastAPI backend.

## Testing

**No frontend tests.** Do not write `*.test.ts` / `*.test.tsx` files or introduce a test runner. We verify the frontend manually in the browser plus `pnpm tsc --noEmit` and `pnpm lint` (**oxlint** — not Biome/ESLint). If you find yourself reaching for vitest, Playwright, or Cypress — stop. That's not what this project does. Correctness for shared logic comes from keeping it simple and well-typed, not from a test suite.

## Anti-patterns (rejected)

- Reading `import.meta.env.X` directly outside `lib/env.ts`.
- Importing an HTTP library when `fetch` would do.
- Mixing client state libraries (Zustand + Jotai + Redux) for one project.
- `any` annotations to silence the type-checker.
- Custom CSS files / styled-components alongside Tailwind for new admin chrome — prefer Tailwind; documented exception is `admin-runs.css`.
- Re-implementing a shadcn primitive by hand.
- Reaching for Next.js, SSR, or any framework that requires a Node server in front of the SPA.
