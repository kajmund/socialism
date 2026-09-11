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

## Word-review live watch (WebSocket)

Connect to `/ws/expertgranskning` with hello `{ type: "hello", scope: "expertgranskning_watch", job_id }`. Auth is the same `access_token` query param as other sockets. The server loads `jobs.kind == expertgranskning_word_review` and calls `assert_kund_access` on `job.customer_id` (4401 / 4403). Unknown or wrong-kind jobs close with 1003.

Server sends `expertgranskning.replay` immediately (`job_id`, `status`, `results[]`), then streams:

| Event | When |
| ----- | ---- |
| `expertgranskning.result.created` | After each result row is committed |
| `expertgranskning.result.updated` | After claim/complete/unresolved (or legacy PATCH `comment_id`) |
| `expertgranskning.finished` | Job succeeded or failed (`status`, optional `error` / `stats`) |

Implementation: `app/realtime/expertgranskning_broadcast.py`, `app/services/expertgranskning/watch.py`. Consumer is `word-addin/` (not the admin SPA). Sideload and host limits: [guides/word-addin.md](guides/word-addin.md).

## generic_panel flow

1. Moderator opening (`panel.moderator.opening`) — one starting question only
2. Competency (always, once per execution):
   - One authoritative decision per expert, carried as `CompetencyState` (`competent` slot set).
   - Standalone sessions take the decision from `panel.expert.research_need` (`has_domain_competence`). Frozen-evidence Attempts use `panel.expert.competency` and **must not** run ResearchPlan / ResearchRouter, mutate evidence, or enable tools.
   - Competence is profile-versus-question. Relevant EvidenceSet material must never manufacture expertise (M&A/PMO stays non-competent for criminal law even with excellent criminal-law evidence).
   - Experts outside the competent set cannot enter the raise-hand queue, receive substantive scratchpad work, or produce expert turns. A later `JA` cannot override a failed competency decision.
   - `competent=true` + `RAISE=NEJ` is distinct from `competent=false`.
3. Research-plan phase (standalone only, before any raise-hand):
   - Each expert first decides domain competence, then identifies research needs (`panel.expert.research_need`, phase `research_need`). Structured output. `has_domain_competence` is required. Out-of-domain experts must not invent domain-specific questions; code drops any needs they still emit and the turn signals missing expertise. Zero needs is valid for a competent expert. Experts do not assess here and do not call tools/MCP.
   - Moderator consolidates a `ResearchPlan` (`panel.moderator.research_plan`, phase `research_plan`): semantic grouping only (`question`, `why_needed`, `proposal_ids`). Permanent IDs (`research_1`, …), `requested_by`, and `source_types` are assigned in code from those proposal IDs (`source_types` is the deterministic union of the included proposals). A real expert draft needs a non-empty question and at least one allowed source type before it receives a `proposal_N` id; empty/whitespace questions are not proposals. Every valid proposal must be consumed exactly once or convergence fails closed. Unknown or invented proposal IDs cannot create a need. One constrained moderator retry (`panel.moderator.research_plan_repair`) is allowed after `InvalidResearchPlanError`; a second failure still fails closed. Code does not auto-group, drop, or invent source types. Persisted needs use the shared `ResearchNeed` / source-type taxonomy in `app.services.research`.
   - Persist on `panel_sessions.research_plan`. An empty plan is valid. If **no** expert has domain competence for the main question, the moderator records `unanswered` (`panel.moderator.missing_expertise`) and skips raise-hand rounds — no analogy rescue. Moderator prose is presentation only; do not parse it as state.
   - `source_types` are logical (`case_knowledge`, `customer_knowledge`, `domain_knowledge`, `swedish_law`, `swedish_preparatory_works`, `web`) — not a concrete MCP/server. `web` is allowed but not the default. No research execution in this phase.
4. For each round (default 2), only when at least one expert has domain competence:
   - Round 2+: moderator asks the next question (`panel.moderator.next_question`, phase `sub_question`) before any expert speaks. Do not keep the discussion going with analogies when competence is missing.
   - Competent experts only: raise-hand (`panel.expert.raise_hand`) → JA/NEJ queue. JA means a substantial assessment of **this** question, not a helpful aside.
   - **Only JA speaks** — raisers get scratchpad + public turn. NEJ is a real abstention. An empty queue is valid.
5. Structured synthesis (`panel.generic.synthesis` via `complete_structured`) → `panel.result` as `PanelResult`
   - Claims are decision-relevant conclusions (`claim_1`, `claim_2`, …), not minutes. `score` is always `None`.
   - `dissensus=true` only for material disagreement on the same question.
   - `unanswered` stays `list[str]` for historical readability. Schema v2 adds `unanswered_items` (`reason = missing_expertise` when no relevant expert) and `competency`. Do not infer `missing_expertise` by parsing moderator prose.
   - Scratchpads are excluded. Raise-hand JA/NEJ is context, never evidence or a claim.

Scratchpads are stored on the session row and included in expert prompts but omitted from the public transcript used for synthesis (recorded as `scratchpad` phase turns).

## dd_panel flow (Fas 2)

1. Create via `POST /dd/campaigns/{id}/panel-sessions` (candidate + expert panel from campaign `expert_panel_id`, or legacy `expert_role_keys`)
2. Spinndoktor opens without naming upcoming sub-questions, then introduces each one when it is that round
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

- `panel_sessions` — config (including frozen `expert_slots` snapshot), transcript JSON, scratchpads, analysis, **research_plan** (generic_panel), **result**
- Optional FKs: `panel_id` → `populations` (`kind=expert_panel`), `project_id` → `projekt` (module-agnostic), `campaign_id` → `dd_campaigns` (DD extra only), `job_id`
- Create with `panel_id` to reuse a saved expert panel; `protocol` stays per session. No silent backfill of `project_id` on legacy rows.
- Prompts live in the database (`prompt_catalog.py` defaults, active configuration at runtime)
- DD-panel Spinndoktor identity comes from the shared `spinndoctor` catalog row (`panel.expert.system`); the session brief is a separate system message, not merged into the identity prompt

## API

- `POST /panel/sessions` — create session (`panel_id` and/or inline `expert_slots`, optional `project_id`)
- `GET /panel/sessions/{id}` — fetch session + transcript
- `POST /panel/sessions/{id}/run` — enqueue `panel_session_run` job
