# Frontend — agent notes

This is the React SPA for **Socialism**. Read [../AGENTS.md](../AGENTS.md) first — universal building rules live there. This file adds frontend-specific conventions.

## Stack

- **Plain React SPA** (Vite + TypeScript, strict). **Not Next.js** — do not suggest Next, SSR, server components, or file-based routing.
- **Tailwind CSS** for styling. No CSS modules, styled-components, Emotion, or `.module.css` files for component styles. Global theme tokens live in `src/index.css`.
- **Admin theme:** Devbrains charcoal + gold via Tailwind tokens + shadcn. Run list/config styles live in `src/styles/admin-runs.css` (`.theme-admin`).
- **shadcn/ui** for UI primitives (admin surfaces). Add components with `pnpm dlx shadcn@latest add <name>` — don't hand-roll what shadcn already ships.
- **React Router** for routing.
- **Auth:** Supabase magic link via `src/lib/auth.ts` + `supabaseClient.ts`. Roles: `admin` (sees Verktyg/configuration), `user`, `bolag`. No Google/SSO.

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
│   ├── lib/               # http, api, auth adapter, env
│   ├── auth/              # AuthProvider + route guards
│   ├── pages/             # Route-level components
│   ├── styles/            # admin-runs.css (dense run-config chrome)
│   ├── App.tsx            # Router
│   ├── main.tsx
│   └── index.css          # Tailwind + Devbrains tokens
├── mockup/                # Visual source of truth (Socialism.zip + extracted/)
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```

Keep imports consistent with the `@/*` alias (e.g. `@/lib/api`, `@/components/ui/button`).

## Admin shell / scrolling (mandatory)

**Nothing may scroll under the sidebar (or the mobile top bar).** The document/`body` must not scroll on admin pages. Content scrolls *inline* in `.admin-main-scroll`.

### Shell contract (`AdminShell` + `admin-runs.css`)

1. **`AdminShell`** is a fixed viewport: left `.admin-sidenav` + `.admin-main-scroll`. Below `lg` a slim `.admin-mobilebar` sits above main and the sidebar is an overlay drawer.
2. **Sidenav is not sticky/fixed over scrolling content on desktop** — it is an in-flow column. Do not use `backdrop-filter` over page content. Keep the opaque charcoal rail.
3. **`.admin-main-scroll`** fills the remaining width/height (`flex: 1; min-width: 0; min-height: 0; overflow: hidden`). Page roots scroll themselves.
4. Direct page roots under main (`.wrap`, `.shell`) get `flex: 1; min-height: 0` and the shared content column `max-width: 1240px` (centered). Default `.wrap` uses `overflow: auto` (whole page scrolls *beside* the sidebar, never behind it). Composer roots (`.shell`) keep `overflow: hidden` and scroll inside their panes.
5. **Full width exception:** only `.wrap.spinndoctor-page` (SpinnDoktorn) may use `max-width: none`. Do not add other full-bleed page roots.
6. **Module links** in the sidenav come from `MODULE_REGISTRY` (`navItems` on each manifest), filtered by the kund’s `available_modules`. Shared links (rapporter, återkoppling, jobb) plus admin (verktyg, användare) stay in the same rail.

### List / long pages — `admin-page`

When a page has a title/filters **and** a long list, do **not** let the list climb into the nav. Use:

```tsx
<div className="wrap admin-page">
  <div className="admin-page-chrome">{/* title, filters, tabs */}</div>
  <div className="admin-page-body">{/* scrollable list / grid / report */}</div>
</div>
```

- `.admin-page` → `overflow: hidden` flex column filling main.
- `.admin-page-chrome` → `flex-shrink: 0` (stays visible beside the sidebar).
- `.admin-page-body` → `flex: 1; min-height: 0; overflow: auto` (inline scroll).

Examples: Kampanjer (lista + kampanjdetalj med flikar), Experter, Expertpaneler (lista + detalj), Jobb, Rapporter, Återkoppling, DD-körning (`dd-run-page admin-page` with Research/Resultat in the body).

Plain `.wrap` (without `admin-page`) still scrolls *beside* the sidebar, but title/tabs scroll away with the content. Prefer `admin-page` whenever the page has chrome that should stay put.

All page roots (`.wrap`, `.shell`, `.admin-page`) share the same content column: `max-width: 1240px`, full main height beside the sidebar. Do not override with inline `maxWidth` / ad‑hoc padding. The only full-bleed exception is SpinnDoktorn (`.wrap.spinndoctor-page`).

### Do not

- Put `sticky` / `fixed` on `.admin-sidenav` so main content paints underneath it on desktop.
- Rely on window/`body` scroll for admin routes.
- Use translucent nav + `backdrop-filter` without an opaque underlay (content will show through when scrolling).
- Invent a second page chrome pattern — extend `admin-page` / `admin-page-body` instead.
- Hardcode module nav links in `AdminShell` — add them on the module manifest.

## i18n / L10n

**Mandatory for all GUI changes.** Any new or updated user-facing UI text must go through i18n — never hardcode Swedish/English strings in components. See also root [../AGENTS.md](../AGENTS.md) → **Frontend i18n (mandatory)**.

Swedish is the default UI locale. Do **not** add `react-i18next` / `lingui` unless catalogs outgrow a small helper.

- Catalogs: `src/i18n/messages/sv.ts` (source of truth for keys) and `en.ts` (same shape).
- Runtime: `LocaleProvider` + `useLocale()` from `@/i18n` (`t(key, params?)`, `locale`, `setLocale`, `intl` for `Intl.*`).
- Persist choice in `localStorage` (`opinionssimulator.locale`); sync `document.documentElement.lang`.
- Language switcher lives in `AdminShell` (bottom of the left sidenav) and on `/login`. Migrated so far: nav, login, Jobs, Runs list/detail/configure/results, Populations list/detail/builder + job toasts, Personas list/composer/card-fields/profile, Messages list/workshop/variants, Config page/map.

**Adding a string**

1. Add the Swedish copy under the right nest in `messages/sv.ts`.
2. Add the English copy for the same key path in `messages/en.ts` (TypeScript enforces matching keys).
3. Replace hardcoded UI text with `const { t } = useLocale(); t("section.key")` (use `{name}` placeholders for interpolation).
4. For dates/numbers, use `intl` from `useLocale()` with `Intl.DateTimeFormat` / `Intl.NumberFormat` — do not hardcode `"sv-SE"`.

Still hardcoded (next slices): OASIS simulation prompts (intentionally Swedish). Report HTML language follows UI locale at order time (`locale` on `POST /reports`).

## Routes (current)

| Path | Status |
|------|--------|
| `/login` | Sign-in (magic link) |
| `/valj-modul` | Redirect → module home (sidebar is how you switch) |
| `/` | Dashboard (startsida) |
| `/runs` | Körningar list |
| `/runs/new`, `/runs/:id/edit` | Körning (wizard / quick + Resultat) |
| `/jobs` | Bakgrundsjobb (population, simulering, report) |
| `/feedback` | Återkoppling (buggar/idéer/åsikter från hjälpchatten) |
| `/reports` | Rapportlista |
| `/reports/:id` | HTML-rapport |
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
Home is `/` (dashboard). Unknown routes redirect to `/`.

## Themes

- **Visual source of truth:** `mockup/extracted/` (pages, `styles.css`, `app.jsx`, Devbrains `_ds/` tokens). New or changed UI — including the report viewer and any report chrome — must follow that style, not a separate aesthetic.
- **Admin theme:** Devbrains charcoal + gold. Dense run-config chrome lives in `src/styles/admin-runs.css` under `.theme-admin`. Use Tailwind + shadcn for new admin chrome where practical, matching the mockup.

## Code style (frontend-specific)

- **TypeScript strict.** No `any` unless there's no alternative; prefer `unknown` and narrow.
- **Small, composable functions and components** over clever abstractions. Three similar lines > a premature generic.
- **One component = one file.** Components stay small enough to fit on one screen.
- **Tailwind classes inline** for admin.
- **Async by default.** Run everything that can be async asynchronously — do not block the UI on work that can finish in the background or in parallel.
  - Prefer backend **jobs** (`POST /jobs`, kind like `population_generate` / `run_simulate` / `report_generate`) over long synchronous API calls; navigate to `/jobs` or subscribe to job updates instead of awaiting heavy work in the page request.
  - When loading independent data, use `Promise.all` (or equivalent) — do not `await` A then B then C if they do not depend on each other.
  - Keep handlers non-blocking: kick off work, show pending/toast state, let the user continue; only serialize steps that truly need prior results.

## Configuration

- All env reads go through a single `src/lib/env.ts` module that validates required vars at boot. Never read `import.meta.env.X` directly in components.
- Env vars are prefixed `VITE_` (Vite convention). Anything not prefixed is not exposed to the client.

## Backend integration

- Talks to a separate Python backend over JSON. URL comes from `VITE_API_BASE_URL`.
- Always use `api.get/post/put/patch/delete` from `@/lib/api` — it handles base URL, JSON, bearer token from `authAdapter.getAccessToken()`, timeouts, and typed `ApiError`s (including the `isNetworkError` flag that distinguishes CORS/network from HTTP errors).
- Auth uses the Supabase magic-link adapter (`authAdapter`). The API client reads the bearer token from `getAccessToken()` — never thread tokens through component props.
- Hide **Verktyg** / configuration routes for `user`. Use `useAuth().isAdmin` (or `canAccessConfiguration`) — do not sprinkle role strings in pages.
- Admin surfaces (personas / populations / runs) talk to the FastAPI backend.

## Testing

CI and `make test-frontend` run `pnpm lint` (**oxlint** — not Biome/ESLint) and `pnpm test` (vitest, existing `src/**/*.test.ts`). Verify UI in the browser. Do not introduce Playwright, Cypress, or a broad component-test suite. Keep any new unit check small and on shared logic — not page-level UI.

## Anti-patterns (rejected)

- Reading `import.meta.env.X` directly outside `lib/env.ts`.
- Importing an HTTP library when `fetch` would do.
- Mixing client state libraries (Zustand + Jotai + Redux) for one project.
- `any` annotations to silence the type-checker.
- Custom CSS files / styled-components alongside Tailwind for new admin chrome — prefer Tailwind; documented exception is `admin-runs.css`.
- Re-implementing a shadcn primitive by hand.
- Reaching for Next.js, SSR, or any framework that requires a Node server in front of the SPA.
