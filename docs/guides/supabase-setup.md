# Supabase setup (later)

**Phase 1 does not use Supabase for product state.** The app runs on SQLite via SQLAlchemy + Alembic (`DATABASE_URL` under `backend/`). The SPA uses a static login adapter until this guide is followed.

This guide is for the **future** migration to Supabase Postgres + email Auth. Keep it as a checklist — do not assume the tables or Auth flows below are live today.

## What stays true

- Alembic in `backend/` remains the schema source of truth (not the Supabase dashboard).
- Frontend already requires placeholder env vars `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` so Auth can be plugged in without reshaping boot validation.
- Backend settings stay in `app/config.py`; frontend env stays in `src/lib/env.ts`.

## 1. Create a project (when ready)

1. Sign up at [supabase.com](https://supabase.com).
2. Create a project (name e.g. `Opinionssimulator`).
3. Save the database password.
4. Pick a region close to your Railway deploy.

## 2. Credentials to collect

| Value | Where | Used by |
| ----- | ----- | ------- |
| Project URL | Project Settings → API | Frontend (+ later backend Auth verify) |
| `anon` public key | Same page | Frontend only |
| `service_role` secret key | Same page | Backend only — never in the browser |
| Direct database URL | Project Settings → Database (session / direct) | Alembic + SQLAlchemy |
| Database password | Set at project creation | Direct Postgres connection |

Keep `service_role` out of git, client bundles, and frontend env files.

## 3. Auth settings (planned)

Target: email auth only — no Google/SSO.

1. Dashboard → Authentication → Providers → Email enabled.
2. For local dev you may disable "Confirm email"; re-enable for production.

## 4. Schema migration path

When switching off SQLite:

1. Point backend `DATABASE_URL` at the **direct/session** Postgres URL (not the transaction pooler) for Alembic.
2. Add a Postgres driver (`psycopg`) when needed.
3. Run `uv run alembic upgrade head` from `backend/`.
4. Expect current models — personas, populations, runs, messages, catalog lists, jobs, reports, persona messages — not a separate document/chunk/citation corpus.

Do not hand-create production tables in the dashboard.

## 5. Frontend wiring (planned)

The SPA already has an `AuthAdapter` (`signIn`, `signOut`, `getSession`, `getAccessToken`) in `frontend/src/lib/auth.ts`. Today it is a static username/password implementation. To switch:

1. Implement the same `AuthAdapter` with `@supabase/supabase-js` (`signInWithPassword`, `getSession`, `signOut`).
2. Map `user.user_metadata.role` (or equivalent) to `"admin" | "user"`.
3. Replace the `authAdapter` export — do not change `AuthProvider`, route guards, or `api.ts`.
4. Treat the login field as email (same input; no register flow unless you add one).
5. Placeholders `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` already satisfy boot.

## Related

- [Backend setup](backend-setup.md) — SQLite today, Postgres swap notes
- [Frontend setup](frontend-setup.md) — required `VITE_SUPABASE_*` placeholders
- [Architecture](../architecture.md) — current phase 1 system
