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
2. **Granska** captures the full document and the chosen task scope in one `Word.run` via `captureWordTaskSnapshot`. Whole-document scope is the default. Selection scope expands the current selection to containing paragraphs using `selection.paragraphs` plus `uniqueLocalId` or range equality — never selected-text search. An empty/collapsed selection fails in the pane before any previous Word comments are resolved. The same immutable `sections` snapshot is sent to `POST /expertgranskning/word-intent-interview` with the selected panel id. Interview rules stay in the system message; the captured document is sent as delimited user data (`<document>…</document>`), not as instructions. The endpoint returns a generic `DocumentIntentInterview` (at most five document-specific questions; no hard-coded document-type flow). The user answers in the pane. Optional free-text `review_intent` stays a separate supplement and is never filled from those answers. `POST /expertgranskning/word-jobs` then carries the same `WordTask` (`review` + `document`/`selection` + panel strategy), the same `sections`, `intent_interview`, `intent_answers`, and optional `review_intent`. Only then are previously applied Word artifacts resolved. The server keeps `sections` as full-document context, prepends structured interview answers plus review intent via `compose_expert_review_context`, and uses `task.scope` to decide which paragraphs may produce WordActions. Headings get the same anchor fields as body paragraphs. After Word restart the add-in has a new session id, so recycled `uniqueLocalId` values are ignored and the resolver continues via exact text → context.
3. The pane opens `/ws/expertgranskning` with hello `{ type: "hello", scope: "expertgranskning_watch", job_id }`.
4. Independent batches and sections run concurrently under `WORD_REVIEW_MAX_CONCURRENCY`. After a section's batches finish, the backend consolidates overlapping observations (same issue, including nearby anchors) into fewer Word comments and keeps real disagreement. That finalized section is persisted and published immediately; later sections continue. Each expert comment must name one allowed `anchor_paragraph_index`; a multi-paragraph question without a valid anchor is dropped rather than copied onto every paragraph. Word structured LLM calls retry once on JSON syntax errors (`json_invalid`); a second failure fails the job. A code-owned materializer turns each semantic result into a persisted `WordAction` (`comment` or `replace`) with a frozen `anchor`. Replay, `action.created`, `action.updated`, and `progress` only upsert the side-pane queue by `action.id` (or update the compact section counter). They never claim or mutate Word. A newly created action is a proposal (`pending` = awaiting an explicit user decision) and can be Applied or Dismissed while the job is still running. Visible cards sort by document `paragraph_index`, not arrival time.
5. The add-in executes generic WordActions only after **Apply**. Comments and replacements use the same resolver (`resolveWordAnchor`): same-session local id + text, then exact captured text. One text match resolves; several require a unique previous/next fingerprint. The original index is only a hint and must not win because duplicate text sits there. Fail closed on `stale` / `ambiguous` / `missing` / `unsupported` — no Word mutation. Apply pre-resolves the anchor, then claims `pending → applying` with an `application_id`, resolves again immediately before mutation, and completes `applying → applied` (or marks `unresolved`). **Dismiss** is an atomic `pending`/`unresolved` → `dismissed` update and never creates a Word artifact. There is no PATCH shortcut. Replay never retries `applying` / `applied` / `dismissed` / `unresolved`. `replace` still uses Track Changes when available.
6. First run writes `socialism_doc_id` to `Office.context.document.settings` and sends it as `doc_id`. Later **Granska** calls `GET /expertgranskning/word-jobs/latest?doc_id=…`. If that job is still `pending`/`running`, the pane reconnects (same on mount) instead of starting another job. `POST /word-jobs` returns **409** `word_review_already_running` for the same `doc_id` while a job is live. A finished job means proposal generation is finished, not that every action is decided. The queue stays visible after the WebSocket closes. On pane reload after a finished job, `latest.actions` are restored for Apply/Dismiss. A new review is blocked while any action is `pending`, `unresolved`, or `applying`. Only previously applied Word artifacts (`word_artifact_id`) are resolved when a new review is allowed to start.

## `insertComment` host support

Comments need **WordApi 1.4** (`paragraph.insertComment`). If the host does not report that requirement set, the pane refuses to start a job and shows an error. This was not exercised in a real Word desktop host in CI — only unit tests for section building and event dedupe.
