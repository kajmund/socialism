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
| S3 access key + secret | Storage → S3 | Backend (`SUPABASE_S3_ACCESS_KEY_ID`, `SUPABASE_S3_SECRET_ACCESS_KEY`) |
| S3 region | Same Storage S3 page | Backend (`SUPABASE_S3_REGION`) — must match the project region |
| Direct database URL | Project Settings → Database | Later: Alembic + SQLAlchemy Postgres |

Keep `service_role` and S3 secrets out of git, client bundles, and frontend env files.

## Storage (S3)

The backend talks to Supabase Storage through the S3-compatible API (`https://<project-ref>.storage.supabase.co/storage/v1/s3`). Create access keys under **Storage → S3**.

One bucket per kund, named `{kund-slug}` (for example `devbrains`, `bolag-demo`). The module is the first folder in the object key. Buckets are created on first upload and when an admin creates or updates a kund. Object keys:

- Annual reports: `{module}/candidates/{candidate_id}/annual-reports/{id}/{filename}`
- Generated reports: `{module}/reports/{report_id}/report.html` (plus `report.slots.json` and `report.dd.json` / `report.ssr.json`)

S3 credentials stay on the backend. The SPA uploads and downloads through FastAPI.

## Research Vector Bucket

The backend uses Supabase Storage Vector Buckets for searchable, persistent research
knowledge. The service-role key authenticates this server-only path; the S3 access keys
are not used for vector queries.

Defaults:

```env
SUPABASE_VECTOR_BUCKET=research-knowledge
SUPABASE_VECTOR_INDEX=documents-openai
SUPABASE_VECTOR_DISTANCE_METRIC=cosine
RESEARCH_QUESTION_SEMANTIC_MATCH_THRESHOLD=0.88
RESEARCH_QUESTION_SEMANTIC_MATCH_LIMIT=8
RESEARCH_QUESTION_EMBEDDING_VERSION=knowledge-question-v1
```

At startup, the research worker creates a missing bucket/index and verifies `float32`,
the configured metric, and `EMBEDDING_DIMENSION`. The dimension must match
`EMBEDDING_MODEL` (3072 for the default `text-embedding-3-large`). A mismatch is a hard
startup error because an existing vector index cannot change dimension or metric.

Canonical `KnowledgeQuestion` embeddings use this same index. A dedicated
vector customer partition and metadata (`knowledge_kind=knowledge_question`
plus the public or tenant namespace) keep question identities separate from
document chunks and from other customers. SQL stores the canonical question
and its embedding model, version, and dimension; the vector match is only a
candidate selector.

`GET /health/research-vector` reports the configured bucket, index, and dimension after
startup. It never returns credentials.

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
