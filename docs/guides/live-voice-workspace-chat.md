# SME workspace chat and ElevenLabs

SME individual expert dialogue uses ElevenLabs Agents for both text (private signed WebSocket URL) and live voice (private WebRTC conversation token). The existing LLM remains the specialist generator for source-bound documents, comparisons and relations; it never runs a second dialogue for this workspace. Panel conversations retain their existing behavior.

## Configuration

Set backend configuration from `backend/.env.example`:

- `ELEVENLABS_API_KEY`: existing server-only provider key with agent/tool/procedure permissions.
- `ELEVENLABS_VOICE_ID`: chosen ElevenLabs voice, suitable for the enabled languages.
- `ELEVENLABS_LLM`: explicitly selected ElevenLabs model. Unavailable/deprecated models fail; automatic backup is disabled.
- `ELEVENLABS_SESSION_TTL_SECONDS`: local session lifetime, separate from provider connection-token lifetime.

Run Alembic to head before starting the service. Migration 149 adds owner-scoped workspaces, sources, stable references, versioned artifacts, idempotent operations, native deployments and conversation events. PostgreSQL uses the existing backend service connection; the new tables are closed to Supabase client roles by RLS. SQLite supports the same model for local tests.

PDF export reuses the existing LibreOffice conversion service. Install LibreOffice on the backend host and set `LIBREOFFICE_BIN` if it is not on PATH. Word exports are generated directly as OOXML and need no new runtime library.

## Activation prerequisite

A read-only audit of the configured database on 2026-10-04 found `alembic_version = 147_expert_async_tool_prompts`. That revision is absent from the current migration graph and its reachable Git history. The canonical chain is `146_lookup_research_evidence_tool` → `147_persona_message_voice_turn` → `148_expert_async_tool_prompts` → `149_live_voice_workspaces`. An ordinary upgrade cannot resolve the current database marker.

The inspected effects of canonical 147–148 are already present: `persona_messages.voice_turn_id` is nullable `varchar(64)`, with `uq_vturn UNIQUE (persona_id, voice_turn_id, role)`; there is no `provider_turn_id` column. Both new tool-ack/result prompt fields are active and match the catalog in Swedish, English and Norwegian. The four prompt defaults updated by 148 also match, and no overrides retain its exact previous text. This verifies those migration effects, not the complete schema or ancestry through 146. No workspace tables exist yet.

Before activation:

1. Stop application writers and take a restorable database backup. Recover the old revision's deployment/migration record and compare a restored copy against the complete canonical schema through 148, including constraints and prompt data. Do not infer equivalence from the similar revision name alone.
2. If that audit confirms the database is fully equivalent to 148, have the operator approve a **version-marker-only reconciliation to `148_expert_async_tool_prompts`**. The repair must handle the unresolvable old marker explicitly; ordinary `alembic stamp` may also reject it. Do not rerun 147 against its existing column, stamp 149, or add a compatibility migration. If the full audit identifies differences, resolve those differences before reconciling the marker.
3. From the checked-out backend, run `alembic upgrade head` with the configured `MIGRATION_DATABASE_URL` owner connection. This is the separate schema change that creates the eleven workspace tables in 149. Runtime `DATABASE_URL` is not the migration credential. The audited URLs target the same database with distinct roles; the runtime role has RLS bypass and direct SELECT/INSERT/UPDATE/DELETE grants in the migration owner's public-schema table defaults, while the migration role owns the inspected tables. Migration 149 preserves those direct runtime grants when revoking client-role and PUBLIC access; RLS bypass alone would not grant table access.
4. Verify the marker is `149_live_voice_workspaces`, all eleven tables and their constraints exist, the runtime role can use them, and RLS plus revoked `PUBLIC`/`anon`/`authenticated` access remains intact. Then start the application and perform the live acceptance checks below.

The audit used read-only transactions. It did not stamp, migrate, modify prompts, or write test data to the configured database.

## Prompt and deployment lifecycle

`workspace.voice.*` and `workspace.generate.*` are module-owned prompt catalog defaults seeded into `prompt_fields`. Runtime loads the customer's effective `prompt_fields` plus `prompt_overrides`. Do not put prompt bodies in environment variables or provider-specific code. Agent deployment captures the effective profile, language, prompts, tool definitions and chosen model/voice. Its published version and prompt fingerprint are stored with each local session.

Bootstrap creates private connection credentials and a persisted session bound to customer, user, workspace, expert, local generation and expiration. All native tools are ElevenLabs client tools. Presentation tools update the UI; data and generation tools call the authenticated local backend and use the same domain services as ordinary workspace commands. Each request verifies the provider conversation binding and active session. The local application needs no publicly reachable webhook or tunnel. A new session revokes the previous generation. Client callbacks also check their generation before changing the displayed chat.

## Persistence and presentation

Workspace state persists selected expert, knowledge scope, document tabs, independent page/zoom, split documents and selected reference/block/node. Updates use an expected revision; concurrent updates return a conflict. Tool operations are idempotent by workspace and operation key. A turn captures the user's workspace selection instead of resolving pronouns against a later click.

Provider deployment, bootstrap, lookup, memory and export each release database connections before external calls. One-connection pool regressions verify this while the external service is pending.

Finalized transcript events are persisted into workspace-bound expert history, separate from public library interviews. Corrections replace the original interrupted reply instead of appending a duplicate. Existing shared customer/expert memory remains readable. Completed workspace turns and consultations write to a separate customer/expert/owner namespace so private document content cannot merge into shared memory. Workspace memory never supplies source citations. Legacy history, admin memory lists and job broadcasts must enforce the same separation.

References capture a stable number, source/version, exact anchor and immutable snapshot. Search, comparison, graph and document content use those same IDs. Source changes make old references stale; generation validates references before queueing and never invents location coordinates. Unsupported graph conclusions must be marked as interpretations. Document and presentation source text is untrusted input.

Generation uses persisted `workspace_generation` jobs and immutable artifact revisions. UI/export commands distinguish queued, running, ready and failed. A selected-block revision is checked to preserve every other block. Word/PDF downloads authorize the owner and explicitly select a saved revision. Interrupted jobs are marked failed after backend restart, matching the existing job runner; research uses its existing durable claims.

Client tools acknowledge presentation only after the requested view/anchor is rendered. Background completion is sent as a contextual update, never a synthetic user utterance. Ending a voice connection does not cancel generation or delete its workspace.

## Verification

Run backend pytest, frontend lint/tests/build and `make knowledge-validate`. The default test suite mocks provider HTTP and LLM boundaries and makes no ElevenLabs calls. Live acceptance requires configured provider credentials, browser microphone access, and provider permission to create private agents/tools/procedures: run both text and WebRTC voice, switch expert/workspace, interrupt an answer, upload/read a source, show its anchor, create/revise/export a draft and confirm no stale callback affects the new session.

The reference UI and detailed acceptance criteria are in [the implementation spec](../specs/live-voice-workspace-chat.md).
