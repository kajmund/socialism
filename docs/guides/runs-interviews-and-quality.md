# Runs: interviews, branches, and quality signals

Developer runbook for körning features that evolved after the first architecture pass: planned tick interviews, post-hoc run-scoped chat, library chat controls, stimulus/control branching, message freeze, lexical convergence warnings, and persona anecdotes.

Verified against `backend/app/api/{runs,personas}.py`, `backend/app/services/{oasis_run,run_tick_context,lexical_convergence}.py`, `backend/app/llm/{chat,persona_anecdote}.py`, and the admin SPA helpers under `frontend/src/api/` + `frontend/src/data/runs.ts`.

Operator-facing how-tos live under [`knowledge/manual/`](../../knowledge/manual/) (Swedish UI). This page is for builders.

## Intent

Operators need to:

1. Ask personas questions **during** a simulation (planned INTERVIEW after a tick’s reaction rounds).
2. Interview a persona **after** a finished attempt, with feed context cut off at a chosen tick.
3. Chat with personas in the library (no run context), including delete/resend.
4. Compare message formulations (`ab`) or stimulus vs silent control (`stimulus_control`).
5. Spot phrase-echo quality issues in OASIS results.

## Three chat scopes

| Scope | Persistence | Identity | API |
| ----- | ----------- | -------- | --- |
| Library chat | `persona_messages` with `run_id IS NULL` | `(persona_id, mode)` | `/personas/{id}/chat`, `/messages`, delete, resend |
| Planned tick interview | OASIS artifact / results trace (not `persona_messages`) | tick `interviews[]` → ManualAction `INTERVIEW` | configured on the run timeline; executed inside `simulate_run` |
| Post-hoc run interview | `persona_messages` with run scope columns | `(persona_id, run_id, attempt_id, variant_id, through_tick_index)` | `/runs/.../interview` |

Migration `009_persona_messages_run_scope` added `run_id`, `attempt_id`, `variant_id`, `through_tick_index` on `persona_messages`.

Library list/chat filters **exclude** run-scoped rows (`run_id.is_(None)`). Do not mix the two threads in one UI surface.

## Planned tick interviews (during OASIS)

Each tick may include:

```json
{
  "key": "iv…",
  "persona_id": "p_…",
  "prompt": "Vad tycker du om det senaste inlägget?"
}
```

Execution order inside a tick (`oasis_run.simulate_run`):

1. Injections (skipped when `silent` or empty)
2. Population reaction rounds (`rounds`, min 1)
3. Planned interviews via `ManualAction(INTERVIEW)` for each resolved `(agent_index, prompt)`
4. Tick marker `time_start` / `time_end` recorded

`resolve_tick_interviews` skips missing personas, empty prompts, and injector agents. Population agents never get `INTERVIEW` in their free action set — interviews are ManualAction only.

Frontend: configure on the tick day modal (`TickDayModal` / timeline). Results UI shows interview activity in the feed.

Requires `SIMULATION_ENGINE=oasis`. With `none`, start still succeeds but attempts are empty — no interview actions run.

## Post-hoc run interviews (after an attempt)

Path prefix:

```text
/runs/{run_id}/attempts/{attempt_id}/variants/{variant_id}/personas/{persona_id}/interview
```

| Method | Purpose |
| ------ | ------- |
| `GET ?through_tick_index=N` | List thread for that scope |
| `POST { "through_tick_index": N, "message": "…" }` | Append user+assistant turns |
| `DELETE ?through_tick_index=N` | Clear that scoped thread |

### Constraints (fail loudly)

- Run must not be `running` → **409**
- `through_tick_index` must be in `variant.tick_markers` and `≤ ticks_run - 1` when `ticks_run > 0` → **400**
- Persona must appear in `variant.agents` with `role != "injector"` → **404**
- Context built by `build_persona_feed_context`: posts/comments with `created_at ≤ tick_markers[N].time_end`, plus the persona’s own non-trivial actions (caps at 20 unique). Prompt states the agent has not seen later ticks.

Example:

```bash
curl -s -X POST "http://localhost:8000/runs/1/attempts/ATT/variants/a/personas/p_x/interview" \
  -H 'content-type: application/json' \
  -d '{"through_tick_index":0,"message":"Hur påverkade debatten dig?"}'
```

Admin UI: `RunPersonaInterviewPanel` on the results surface.

## Library chat controls

| Endpoint | Behavior |
| -------- | -------- |
| `POST /personas/{id}/chat` | `{ mode: "interview"\|"character", message }` — persists user+assistant |
| `GET /personas/{id}/messages?mode=` | Library thread only |
| `DELETE /personas/{id}/messages?mode=` | Clear library thread |
| `DELETE /personas/{id}/messages/{message_id}` | Delete one library message |
| `POST /personas/{id}/messages/{message_id}/resend` | Truncate from that message forward and regenerate |

Resend rules:

- Target must be library-scoped (`run_id` null).
- If target is a **user** turn: keep history before it, replay that user message, write new user+assistant.
- If target is an **assistant** turn: require the previous kept row to be user; regenerate assistant only.
- Otherwise **400** (`Kan inte regenerera utan föregående användarmeddelande`).

## Branch modes

`variant_plans(run)` returns one or two simulation plans:

| Mode | Variant ids | Labels | Tick composition |
| ---- | ----------- | ------ | ---------------- |
| *(no branch)* | `main` | Huvudtidslinje | `main_ticks` |
| `ab` | `a`, `b` | Version A / Version B | stem `main[:afterIndex+1]` + branch ticks (`afterIndex: -1` = no stem, A/B from day 1) |
| `stimulus_control` | `a`, `b` | Med stimulus / Kontroll (ingen injektion) | same stem+branch split; **labels only** change on the backend |

Important: the backend does **not** strip injections from control ticks. The admin UI builds control via `makeStimulusControlBranch` — B ticks are silent copies (`silent: true`, `injections: []`). API clients must do the same if they want a real control arm.

Silent ticks still run population reaction rounds; they skip new injections.

## Message freeze on start

`POST /runs/{id}/start` calls `_snapshot_message_bodies` before enqueueing `run_simulate`:

- Collects `message_id` from injections on `main_ticks` and branch `a`/`b`
- Loads library `Message` rows; missing ids → **400**
- Copies current `Message.body` into `Injection.text` on the run JSON

Edits to the budskapsbibliotek after start do not change that attempt’s frozen injection text.

## Lexical convergence (`quality_warnings`)

After OASIS readback, each variant gets:

```python
"quality_warnings": analyze_lexical_convergence(
    posts=…, comments=…, agents=…, injection_texts=…
)
```

From `app/services/lexical_convergence.py`:

- Default agent-share threshold: **0.40** (`CONVERGENCE_AGENT_SHARE_THRESHOLD`)
- N-grams 3–6 words (+ 2-word content-word anchors)
- Coarse Swedish normalization (case + suffix stripping) — not full lemmatization
- Warning kinds:
  - `source_phrase_echo` — population reuses phrases from injections
  - `cross_agent_convergence` — shared phrases across ≥ threshold share of population agents
- Payload shape: `{ threshold, population_agents, warnings: [...] }` (internal `phrase_key` stripped)

Surfaced in admin results (`OasisResultsPanel`). Treat as a quality signal, not a hard failure.

## Persona anecdotes (`anekdot`)

Generated on persona/population generate paths (`app/llm/persona_anecdote.py`):

- Schema: 8–220 chars, validator also enforces ≤ **20 words**
- Usability filter: 4–20 words, no political markers / party name
- LLM path retries structured completion up to **3** times for a usable anecdote; if still unusable, returns the last LLM string or a stub template
- Stub generator (`PERSONA_GENERATOR=stub` / population stub path) uses deterministic local templates
- Population generation passes previous anecdotes so new ones try to differ

Chat prompts include a non-empty `anekdot` as `Vardagsdetalj` when present.

## Frontend touchpoints

| Surface | Code |
| ------- | ---- |
| Post-hoc interview panel | `components/runs/RunPersonaInterviewPanel.tsx` |
| Tick interview config | `TickDayModal` / `TickTimeline` / `runs.ts` helpers |
| Stimulus/control branch factory | `makeStimulusControlBranch` in `data/runs.ts` |
| Results + quality warnings | `OasisResultsPanel.tsx` |
| Library chat + resend | `PersonaComposerPage` + `api/personas.ts` |
| Run interview API client | `api/runs.ts` (`list` / `run` / `clear`) |

## Troubleshooting

| Symptom | Likely cause |
| ------- | ------------ |
| Post-hoc interview 409 | Run still `running` — wait for job |
| Post-hoc interview 400 `through_tick_index…` | Tick index past markers / `ticks_run` |
| Post-hoc interview 404 persona | Persona not in that variant’s population agents (or is injector) |
| Planned interviews never appear | `SIMULATION_ENGINE=none`, empty prompts, or persona_id not in population |
| Control arm still got injections | Branch ticks for `b` were not silent — UI factory not used / API payload wrong |
| Library chat missing run interview turns | Expected — scopes are separate (`run_id` null vs set) |
| Resend 400 | Tried to regenerate assistant without a preceding user message |
| `quality_warnings` empty | Below threshold, too few population agents, or no shared n-grams |

## Related

- [Architecture](../architecture.md) — domain + lifecycle overview
- [Backend setup](backend-setup.md) — env, jobs, OASIS install
- [Frontend setup](frontend-setup.md) — routes and themes
- Operator guides: `knowledge/manual/lasa-simuleringsresultat.md`, `konfigurera-dag-i-tidslinjen.md`, `skapa-och-redigera-persona.md`
