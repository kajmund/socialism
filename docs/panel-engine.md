# Panel engine (Fas 1)

Domain layer for multi-expert panel sessions, separate from OASIS tick-loop / `simulation.db`.

## Protocols

| Protocol | Status | Description |
| -------- | ------ | ----------- |
| `generic_panel` | Fas 1 | Moderator + 3–4 experts, turn-taking, scratchpads, session analysis |
| `dd_panel` | Fas 2 | DD scoring matrix (4 sub-questions × experts), Spinndoktor moderator, source badges |
| Focus group | Later | Third protocol; does not replace the above |

## Architecture

```text
POST /panel/sessions          → PanelSession row (draft)
POST /panel/sessions/{id}/run → Job kind panel_session_run (202)
jobs.py                       → PROTOCOL_METHODS → generic_panel / structured_scoring (live turns via panel.watch)
/ws/panels                    → panel_watch replay + fan-out (panel.replay, turn.*, panel.finished)
prompt_store                  → panel.* keys in active configuration
```

Reuses existing job worker, prompt store, LLM `complete_text`, and the same realtime pattern as run watch — not the OASIS simulation engine.

## Live watch (WebSocket)

Connect to `/ws/panels` with hello scope `panel_watch` and `session_id`. Server sends `panel.replay` immediately (status, expert slots, transcript turns), then streams:

| Event | When |
| ----- | ---- |
| `turn.started` | Before LLM produces a turn |
| `turn.completed` | After turn persisted to `panel_sessions.transcript` |
| `panel.finished` | Job succeeded or failed (`status`, optional `error`) |

Implementation: `app/realtime/panel_broadcast.py`, `app/services/panel/watch.py`, frontend `usePanelWatchSocket` + `PanelLiveFeedPanel`.

## generic_panel flow

1. Moderator opening (`panel.moderator.opening`)
2. For each round (default 2):
   - Each expert: raise-hand (`panel.expert.raise_hand`) → JA/NEJ queue
   - Turn order: experts who raised hand first, then the rest (round-robin among non-queued)
   - **All experts speak every round** — raise-hand only affects speaking order, not whether an expert gets the floor. Intentional for DD-style panels where every role should contribute each round.
   - Per expert: scratchpad update → public turn
3. Moderator analysis (`panel.moderator.analysis`)

Scratchpads are stored on the session row and included in expert prompts but omitted from the public transcript flow order (recorded as `scratchpad` phase turns).

## dd_panel flow (Fas 2)

1. Create via `POST /dd/campaigns/{id}/panel-sessions` (candidate + expert panel from campaign `expert_panel_id`, or legacy `expert_role_keys`)
2. Spinndoktor opens and introduces each sub-question
3. Four sub-questions (finansiell hälsa, legal risk, marknadsposition, integrationsrisk)
4. Per sub-question: each expert raise-hand (`panel.dd.expert.raise_hand`) — only those who answer JA score that question
5. If nobody raises a hand: skip scoring, Spinndoktor explains the coverage gap (`panel.dd.moderator.no_answer`, phase `unanswered`)
6. Participating experts score 1–10 with motivation + source badge
7. Structured output in `panel_sessions.result` (`DdPanelResult`: scores matrix, dissensus notes, unanswered notes, summary)

### Source attribution (explicit priority chain)

Implemented in `app/services/dd/source_attribution.py` — **not** silent fallbacks:

1. Candidate figures already in the brief — labeled **Grunddata** for every sub-question that uses those numbers. Do not run a parallel web search to decorate the badge.
2. An actual web/wiki tool result from the scoring turn — labeled **Webb** (only when grunddata figures are missing)
3. `llm` — labeled **Modellbedömning** when no figures and no web tool result

Badges are stored per score in `result.scores[].source`.

## DD report (Fas 3)

1. `POST /reports` with `mode=dd` (auto-inferred) and source `{type: "dd_session", session_id, candidate_id}`
2. Validation requires `PanelSession.status == succeeded`, `protocol == dd_panel`, and matching `candidate_id`
3. Job `report_generate` renders `panel_sessions.result` via `app/services/report/dd_report.py` (no SSR / no new scoring)
4. Artifacts: `report.html`, `report.slots.json`, `report.dd.json` under `data/reports/{id}/`

Source badge colors in HTML: `web` → blue (`web`), `llm` → gray (`single`).

## Persistence

- `panel_sessions` — config, transcript JSON, scratchpads, analysis, **result** (dd_panel), optional `campaign_id`, `job_id`
- Prompts live in the database (`prompt_catalog.py` defaults, active configuration at runtime)

## API

- `POST /panel/sessions` — create session
- `GET /panel/sessions/{id}` — fetch session + transcript
- `POST /panel/sessions/{id}/run` — enqueue `panel_session_run` job
