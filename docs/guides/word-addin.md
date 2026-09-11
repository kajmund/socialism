# Word add-in (expertgranskning)

Sideloaded Office task pane in `word-addin/`. It talks to the FastAPI backend and `/ws/expertgranskning`. The admin SPA is unchanged.

## Local run

```bash
cd word-addin
cp .env.example .env
pnpm install
# Once per machine: HTTPS certs Word will trust
npx --yes office-addin-dev-certs install
pnpm dev
```

Vite listens on `https://localhost:3000` when `~/.office-addin-dev-certs` exists, otherwise HTTP (browser-only). Sideload `word-addin/manifest.xml` in **Word desktop** (Windows or Mac). Word on the web is not the target host for this phase.

Backend CORS defaults include `https://localhost:3000`. Keep `make backend` running and include those origins in `ALLOWED_ORIGINS` if you override the env list.

## Auth

Paste a Supabase magic-link access token once. It is stored in the task pane `localStorage` (Word Mac `roamingSettings.saveAsync` hangs) and sent as `Authorization: Bearer` and as the WebSocket `access_token` query param.

## Review flow

1. Dropdown: `GET /populations?kind=expert_panel` (already kund-filtered).
2. **Granska** reads `context.document.body.paragraphs` (and `uniqueLocalId` when WordApi 1.6 is present), groups sections on Heading 1 / Rubrik 1, and `POST /expertgranskning/word-jobs` with every raw paragraph plus optional session-local ids and a process-local `word_session_id`. The server derives deterministic text/context hashes from that frozen snapshot. Headings get the same anchor fields as body paragraphs. After Word restart the add-in has a new session id, so recycled `uniqueLocalId` values are ignored and the resolver continues via index → exact text → context.
3. The pane opens `/ws/expertgranskning` with hello `{ type: "hello", scope: "expertgranskning_watch", job_id }`.
4. After experts comment, the backend consolidates overlapping observations (same issue, including nearby anchors) into fewer Word comments and keeps real disagreement. Each expert comment must name one allowed `anchor_paragraph_index`; a multi-paragraph question without a valid anchor is dropped rather than copied onto every paragraph. Word structured LLM calls retry once on JSON syntax errors (`json_invalid`); a second failure fails the job. Each result exposes a code-owned `anchor` from the frozen request. Replay and `result.created` may auto-apply only `pending` rows. `result.id` is still process-deduped, but the backend application status is authoritative.
5. Comments and rewrites use the same resolver (`resolveWordAnchor`): same-session local id + text, then original index + exact text, then unique exact text, then previous/next hashes. Fail closed on `stale` / `ambiguous` / `missing` — no Word mutation. Before mutating, the add-in claims `pending → applying` with an `application_id`, then completes `applying → applied` (or marks `unresolved`). There is no PATCH shortcut. Replay of `applying` / `applied` / `unresolved` never auto-applies again. Rewrites still use Track Changes when available.
6. First run writes `socialism_doc_id` to `Office.context.document.settings` and sends it as `doc_id`. Later **Granska** calls `GET /expertgranskning/word-jobs/latest?doc_id=…`. If that job is still `pending`/`running`, the pane reconnects (same on mount) instead of starting another job. `POST /word-jobs` returns **409** `word_review_already_running` for the same `doc_id` while a job is live. A finished job is resolved in Word, then a new job starts.

## `insertComment` host support

Comments need **WordApi 1.4** (`paragraph.insertComment`). If the host does not report that requirement set, the pane refuses to start a job and shows an error. This was not exercised in a real Word desktop host in CI — only unit tests for section building and event dedupe.
