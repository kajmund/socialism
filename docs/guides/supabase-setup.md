# Supabase setup

Auth (magic link) is being wired in phases; Postgres for product state remains later.
SQLAlchemy models + Alembic stay the schema source of truth.

## Credentials

| Value | Where | Used by |
| ----- | ----- | ------- |
| Project URL | Project Settings → API | Frontend (`VITE_SUPABASE_URL`) + backend (`SUPABASE_URL`) |
| `anon` public key | Same page | Frontend only (`VITE_SUPABASE_ANON_KEY`) |
| `service_role` secret key | Same page | Backend only (`SUPABASE_SERVICE_ROLE_KEY`) — never in the browser |
| JWT Secret | Project Settings → API → JWT Secret | Backend (`SUPABASE_JWT_SECRET`) — HS256 verify |
| Direct database URL | Project Settings → Database | Later: Alembic + SQLAlchemy Postgres |

Keep `service_role` out of git, client bundles, and frontend env files.

## Auth settings

Target: magic link (email OTP) only — no Google/SSO, no password management in-app.

1. Dashboard → Authentication → Providers → Email enabled.
2. Enable magic link / OTP sign-in.
3. Set Site URL / redirect URLs to the SPA origin (local Vite + Railway frontend).

## Schema

`user_accounts` (Alembic `045_user_accounts`) stores role + kund binding. Supabase
`auth.users` proves identity; our DB decides what the user may do. No self-signup —
admins invite users (later phase).

## Related

- [Backend setup](backend-setup.md) — required Supabase env vars
- [Frontend setup](frontend-setup.md) — required `VITE_SUPABASE_*`
- [Architecture](../architecture.md) — current system
