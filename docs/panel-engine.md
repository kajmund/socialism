# Panel engine (Fas 1)

Domain layer for multi-expert panel sessions, separate from OASIS tick-loop / `simulation.db`.

## Protocols

| Protocol | Status | Description |
| -------- | ------ | ----------- |
| `generic_panel` | Fas 1 | Moderator + 3–4 experts, turn-taking, scratchpads, session analysis |
| `dd_panel` | Fas 2 | DD-specific protocol on top of shared engine |
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
   - Turn order: queue first, then round-robin
   - Per expert: scratchpad update → public turn
3. Moderator analysis (`panel.moderator.analysis`)

Scratchpads are stored on the session row and included in expert prompts but omitted from the public transcript flow order (recorded as `scratchpad` phase turns).

## Persistence

- `panel_sessions` — config, transcript JSON, scratchpads, analysis, optional `campaign_id`, `job_id`
- Prompts live in the database (`prompt_catalog.py` defaults, active configuration at runtime)

## API

- `POST /panel/sessions` — create session
- `GET /panel/sessions/{id}` — fetch session + transcript
- `POST /panel/sessions/{id}/run` — enqueue `panel_session_run` job
