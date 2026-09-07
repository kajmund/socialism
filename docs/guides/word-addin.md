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

Paste a Supabase magic-link access token once. It is stored in `Office.context.roamingSettings` and sent as `Authorization: Bearer` and as the WebSocket `access_token` query param.

## Review flow

1. Dropdown: `GET /populations?kind=expert_panel` (already kund-filtered).
2. **Granska** reads `context.document.body.paragraphs`, groups sections on Heading 1 / Rubrik 1, and `POST /expertgranskning/word-jobs` with every raw paragraph (the server owns the skip filter).
3. The pane opens `/ws/expertgranskning` with hello `{ type: "hello", scope: "expertgranskning_watch", job_id }`.
4. Replay and `result.created` insert Word comments. `result.id` is deduped so a row that appears in both is inserted once. After `insertComment`, the add-in `PATCH`es `comment_id` (the echoed `result.updated` must not insert again).
5. Rows with `is_rewrite_suggestion` are not ordinary comments. The add-in turns on `changeTrackingMode = trackAll` temporarily, replaces the paragraph if it still matches `reviewed_text`, and inserts the motivering as a comment. If the paragraph moved or change tracking is unavailable, it inserts a comment (`Föreslagen omskrivning: …`) instead of forcing a replace. The original tracking mode is always restored.
6. First run writes `socialism_doc_id` to `Office.context.document.settings` and sends it as `doc_id`. Later **Granska** calls `GET /expertgranskning/word-jobs/latest?doc_id=…`. If that job is still `pending`/`running`, the pane reconnects (same on mount) instead of starting another job. `POST /word-jobs` returns **409** `word_review_already_running` for the same `doc_id` while a job is live. A finished job is resolved in Word, then a new job starts.

## `insertComment` host support

Comments need **WordApi 1.4** (`paragraph.insertComment`). If the host does not report that requirement set, the pane refuses to start a job and shows an error. This was not exercised in a real Word desktop host in CI — only unit tests for section building and event dedupe.
