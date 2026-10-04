# SME workspace chat and ElevenLabs

SME individual expert dialogue uses ElevenLabs Agents for both text (private signed WebSocket URL) and live voice (private WebRTC conversation token). The existing LLM remains the specialist generator for source-bound documents, comparisons and relations; it never runs a second dialogue for this workspace. Panel conversations retain their existing behavior.

## Configuration

Set backend configuration from `backend/.env.example`:

- `ELEVENLABS_API_KEY`: existing server-only provider key with agent/tool/procedure permissions.
- `ELEVENLABS_VOICE_ID`: chosen ElevenLabs voice, suitable for the enabled languages.
- `ELEVENLABS_LLM`: explicitly selected ElevenLabs model. Unavailable/deprecated models fail; automatic backup is disabled.
- `ELEVENLABS_SESSION_TTL_SECONDS`: local session lifetime, separate from provider connection-token lifetime.

Run Alembic to head before starting the service. Migration 151 adds owner-scoped voice workspaces, sources, stable references, versioned artifacts, idempotent operations, native deployments and conversation events. PostgreSQL uses the existing backend service connection; the new tables are closed to Supabase client roles by RLS. SQLite supports the same model for local tests.

PDF export reuses the existing LibreOffice conversion service. Install LibreOffice on the backend host and set `LIBREOFFICE_BIN` if it is not on PATH. Word exports are generated directly as OOXML and need no new runtime library.

## Activation

The application uses the company/client workspace and private chat model introduced by migrations 149–150. Migration 151 adds the owner-bound voice canvas and its source references, artifacts, operations and conversation sessions. Each voice canvas binds a parent workspace and a private core chat; membership is checked on every access and again after external work. The existing company/client APIs and chat/document/research behavior remain available. Voice APIs use `/voice-workspaces`, alongside the company/client `/workspaces` APIs.

A read-only audit on 2026-10-04 verified the canonical schema, prompt updates, parent IDs and migration-owner/runtime privileges. The earlier unresolvable marker `147_expert_async_tool_prompts` had already been corrected to canonical 148, and the project subsequently applied 149–150. No marker correction is needed for voice activation. The application schema/data backup is stored locally with restricted permissions, outside Git. Apply only the pending migration 151 using the owner credential `MIGRATION_DATABASE_URL`, then verify all eleven new tables, their parent/chat constraints, RLS and runtime DML access.

The separate runtime role has direct SELECT/INSERT/UPDATE/DELETE grants in the migration owner's public-schema table defaults. Migration 151 preserves those grants while revoking PUBLIC/anon/authenticated access. RLS bypass alone would not grant table access. All private voice history and memory remain scoped to the owner and selected parent workspace; changing or revoking membership changes access immediately.

## Prompt and deployment lifecycle

`workspace.voice.*` and `workspace.generate.*` are module-owned prompt catalog defaults seeded into `prompt_fields`. Runtime loads the customer's effective `prompt_fields` plus `prompt_overrides`. Do not put prompt bodies in environment variables or provider-specific code. Agent deployment captures the effective profile, language, prompts, tool definitions and chosen model/voice. Its published version and prompt fingerprint are stored with each local session.

Bootstrap creates private connection credentials and a persisted session bound to customer, user, workspace, expert, local generation and expiration. All native tools are ElevenLabs client tools. Presentation tools update the UI; data and generation tools call the authenticated local backend and use the same domain services as ordinary workspace commands. Each request verifies the provider conversation binding and active session. The local application needs no publicly reachable webhook or tunnel. A new session revokes the previous generation. Client callbacks also check their generation before changing the displayed chat.

## Persistence and presentation

Workspace state persists selected expert, knowledge scope, document tabs, independent page/zoom, split documents and selected reference/block/node. Updates use an expected revision; concurrent updates return a conflict. Tool operations are idempotent by workspace and operation key. A turn captures the user's workspace selection instead of resolving pronouns against a later click.

Provider deployment, bootstrap, lookup, memory and export each release database connections before external calls. One-connection pool regressions verify this while the external service is pending.

Finalized transcript events are persisted into workspace-bound expert history, separate from public library interviews. Corrections replace the original interrupted reply instead of appending a duplicate. Existing shared customer/expert memory remains readable. Completed workspace turns and consultations write to a separate customer/expert/owner/parent-workspace namespace so private document content cannot merge into shared memory. Workspace memory never supplies source citations. Legacy history, admin memory lists and job broadcasts must enforce the same separation.

The private canvas inbox reads native events joined to their owner-bound sessions and exposes previews, timestamps and unread counts through `/voice-workspaces/{id}/inbox`. Read cursors use a separate `voice_expert` namespace keyed by canvas and expert; legacy interview and panel cursors cannot mark private history read. The company-only Interview dialog retains earlier company interviews, image questions and follow-up suggestions. Opening it ends the current native conversation.

References capture a stable number, source/version, exact anchor and immutable snapshot. Search, comparison, graph and document content use those same IDs. Source changes make old references stale; generation validates references before queueing and never invents location coordinates. Unsupported graph conclusions must be marked as interpretations. Document and presentation source text is untrusted input.

Generation uses persisted `workspace_generation` jobs and immutable artifact revisions. UI/export commands distinguish queued, running, ready and failed. A selected-block revision is checked to preserve every other block. Word/PDF downloads authorize the owner and explicitly select a saved revision. Interrupted jobs are marked failed after backend restart, matching the existing job runner; research uses its existing durable claims.

Client tools acknowledge presentation only after the requested view/anchor is rendered. Background completion is sent as a contextual update, never a synthetic user utterance. Ending a voice connection does not cancel generation or delete its workspace.

Direct reads create a whole-document reference (`locator=document`) without fabricated page coordinates. PDF display accepts that reference after rendering, while `focus_anchor` requires a localized passage reference and a visible matching marker. An anchor failure leaves the rendered document available and is returned to the native tool caller. Reopening an already displayed source revalidates its presentation for the new workspace revision.

Workspace search retrieves original PDF bytes once per selected source. Q&A discovery keeps its validated original quote and locator for the displayed citation; generated answer text cannot supply highlight coordinates. A failed document ingest can be retried explicitly through `ingest_source` or **Try again** beside the source. The retry queues the normal worker and atomically binds its new job to the same original source.

PDF quote geometry uses visual reading order rather than draw-command order. Matching requires one unique contiguous sequence of whole words, preserves punctuation and applies the existing case and whitespace normalization. An absent, partial-word or repeated quote, or a wrong page, produces no marker. Geometry belongs to the citation anchor identity, so a new search can create a correctly localized reference without rewriting an older citation.

Manual PDF selections verify the characters at the selected page rectangles against the original PDF. A selection within one column can be valid even when the flattened page text interleaves another column. Browser and parser layout whitespace is excluded from character comparison; all other characters and their order must match those original positions, with the existing case normalization. The server saves its original quote, verifies changed anchors again and rejects unverifiable text, page or geometry. Successful verification creates an immutable version-bound reference, reused for unchanged selections during zoom and other state changes. The read transaction ends before object storage and PDF parsing; workspace access and source version are checked again afterward, before saving the reference and state.

## Verification

Run backend pytest, frontend lint/tests/build and `make knowledge-validate`. The default test suite mocks provider HTTP and LLM boundaries and makes no ElevenLabs calls. Live acceptance requires configured provider credentials, browser microphone access, and provider permission to create private agents/tools/procedures: run both text and WebRTC voice, switch expert/workspace, interrupt an answer, upload/read a source, show its anchor, create/revise/export a draft and confirm no stale callback affects the new session.

A real provider smoke published four native procedures and 21 client tools, completed a private text → authenticated local tool → provider reply roundtrip, persisted its history, and minted a private voice token for the same published version. Temporary provider resources were removed. Tool cleanup uses the provider's documented `force=true` only for deployment-owned tool IDs, because agent deletion alone can leave branch dependencies. Browser microphone/audio acceptance is a separate runtime check.

The reference UI and detailed acceptance criteria are in [the implementation spec](../specs/live-voice-workspace-chat.md).
