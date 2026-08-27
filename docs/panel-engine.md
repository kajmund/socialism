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
jobs.py                       → panel.engine.run_generic_panel()
prompt_store                  → panel.* keys in active configuration
```

Reuses existing job worker, prompt store, and LLM `complete_text` — not the OASIS simulation engine.

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

1. Create via `POST /dd/campaigns/{id}/panel-sessions` (candidate + expert roles from `dd_expertpanel` catalog)
2. Spinndoktor (`spinndoctor.system`) moderates — not `panel.moderator.system`
3. Four sub-questions (finansiell hälsa, legal risk, marknadsposition, integrationsrisk)
4. Each expert scores each sub-question (1–10) with motivation + source badge
5. Structured output in `panel_sessions.result` (`DdPanelResult`: scores matrix, dissensus notes, summary)

### Source attribution (explicit priority chain)

Implemented in `app/services/dd/source_attribution.py` — **not** silent fallbacks:

1. OKF manual (`knowledge/manual`)
2. Web (DuckDuckGo)
3. `llm` — labeled **Modellbedömning** when no external source is found

Badges are stored per score in `result.scores[].source`.

## DD report (Fas 3)

1. `POST /reports` with `mode=dd` (auto-inferred) and source `{type: "dd_session", session_id, candidate_id}`
2. Validation requires `PanelSession.status == succeeded`, `protocol == dd_panel`, and matching `candidate_id`
3. Job `report_generate` renders `panel_sessions.result` via `app/services/report/dd_report.py` (no SSR / no new scoring)
4. Artifacts: `report.html`, `report.slots.json`, `report.dd.json` under `data/reports/{id}/`

Source badge colors in HTML: `okf` → green (`confirmed`), `web` → blue (`web`), `llm` → gray (`single`).

## Persistence

- `panel_sessions` — config, transcript JSON, scratchpads, analysis, **result** (dd_panel), optional `campaign_id`, `job_id`
- Prompts live in the database (`prompt_catalog.py` defaults, active configuration at runtime)

## API

- `POST /panel/sessions` — create session
- `GET /panel/sessions/{id}` — fetch session + transcript
- `POST /panel/sessions/{id}/run` — enqueue `panel_session_run` job
