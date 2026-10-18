# Step B: live expert-orchestration channel parity

## Method

The 50 frozen document-presentation cases were each run once through text,
fixed-transcript 1:1 Voice, and Group Voice. All 150 turns entered
`execute_expert_turn`, used the production `find_documents` handler and
delivery adapters, and retained their first stochastic outcome. No failed case
was retried.

The benchmark used an ephemeral SQLite database and production OverGraph
fixtures. Admission, fence ownership, terminal status, and normal turn
execution remained active. Periodic lease renewal was delayed for this
benchmark because SQLite permits only one writer and otherwise introduces a
database-lock artifact that is not present in the PostgreSQL runtime.

The complete local artifact is
`backend/data/document-channel-parity-step-b-v3.json`. The concise,
reviewable result is frozen in
`backend/tests/integration/baselines/document-channel-parity-step-b-v1.json`.

## Result

The acceptance gate failed. Only 28 of 150 channel cases were strictly correct
against the frozen expected selection, mode, presentation decision, and
error-free execution:

- Text: 14/50 strict; 43/50 selections; 37/50 modes.
- 1:1 Voice: 14/50 strict; 42/50 selections; 33/50 modes.
- Group Voice: 0/50 strict; no `find_documents` call in any case.
- Presentation: zero false automatic galleries, but all 75 explicit gallery
  requests were missed.
- External/model failures: 45 total, including 17 structured-output failures
  and 28 Group Voice turns that produced no reply.
- Text and 1:1 Voice returned identical source IDs in 45/50 paired cases, but
  identical `find_documents` arguments in only 34/50.

Median/P95 latency was 10.99/14.70 seconds for text, 10.44/14.71 seconds for
1:1 Voice, and 29.50/32.41 seconds for Group Voice.

## Failure classification

Structured follow-up state is not preserved reliably. Expected `within`
became `filter` in 6 text and 9 voice cases. Other transitions incorrectly
changed `filter` to `replace`, `replace` to `extend`, or issued a second
replacement search.

Group Voice is not semantically equivalent to the other adapters: its extra
group context resulted in zero document-search calls and 28 no-reply tool
episodes. This is separate from the Step A delivery defects (missing turn
correlation, non-floor delivery, and delivery after cancellation), which
remain unresolved.

The absence of false automatic displays is not a passing presentation result:
no channel delivered a gallery at all, including every explicit “visa” case.

## Decision

Do not change production behavior or reintroduce the deterministic
presentation fast path. Investigate the shared presentation continuation,
structured `filter`/`within`/`extend` state, Group Voice context/tool exposure,
and structured-output failures as separate defects. Re-run Step A before any
new Step B acceptance run.

## Post-fix rerun (v2)

After the targeted orchestration fixes (call-ID ownership, panel lease commit,
active-set mode normalization, release of `tool_choice=required` after
presentation), the live 150-turn artifact is
`backend/data/document-channel-parity-step-b-v4.json` and the frozen summary is
`backend/tests/integration/baselines/document-channel-parity-step-b-v2.json`.

| Metric | v1 | v2 |
| --- | ---: | ---: |
| Strictly correct | 28 | 87 |
| Missed explicit shows | 75 | 0 |
| External/model errors | 45 | 2 |
| Erroneous auto displays | 0 | 30 |
| Group Voice median latency | 29.5 s | 2.8 s |

Missed galleries are fixed. Remaining acceptance blockers are presentation
intent on ambiguous/analyze turns and mode transitions beyond content-only
`replace`→`filter` coercion. The deterministic fast path remains unapproved.

## Post-IntentDecision rerun (v3)

After locking a shared `IntentDecision` (`operation`, `presentation`, `scope`,
`query`) before tool execution — without an extra LLM call — the live 150-turn
artifact is `backend/data/document-channel-parity-step-b-v5.json` and the frozen
summary is
`backend/tests/integration/baselines/document-channel-parity-step-b-v3.json`.

| Metric | v2 | v3 |
| --- | ---: | ---: |
| Strictly correct | 87 | 149 |
| Missed explicit shows | 0 | 0 |
| Erroneous auto displays | 30 | 0 |
| Wrong mode transitions | 43 | 0 |
| External/model errors | 2 | 1 |
| Group Voice median latency | 2.8 s | 2.6 s |

Presentation `none`/`uncertain` no longer auto-opens a gallery after
`find_documents`. Operation is forced into `find_documents` mode so
`filter`/`within`/`extend`/`replace` are not re-guessed per tool call.

The remaining failure is one text turn (`21-ambiguous`) with
`ChatTurnError: Expert tool episode produced no reply`. The two v2
`BadRequestError` cases were both `param=response_format` /
`wrong_api_format` (structured-output adherence), not tool-schema rejects;
they did not recur. Deterministic fast path remains unapproved.

## Quality baseline (v4)

After fixing empty continuation when presentation is blocked (text-reply
notice, drop repeated `find_documents` under `none`/`uncertain`, final
text-only recovery) and locking IntentDecision `query` into
`find_documents`, the live artifact is
`backend/data/document-channel-parity-step-b-v8.json` and the frozen
summary is
`backend/tests/integration/baselines/document-channel-parity-step-b-v4.json`.

| Metric | v3 | v4 |
| --- | ---: | ---: |
| Strictly correct | 149 | **150** |
| Erroneous auto displays | 0 | 0 |
| Wrong mode transitions | 0 | 0 |
| External/model errors | 1 | **0** |

**Approved:** IntentDecision and the shared channel orchestration, as the
quality baseline for further latency experiments.

**Not approved:** deterministic presentation fast path. Next experiment may
compare a deterministic continuation against this baseline without changing
presentation or mode rules.

## Query lock refinement

The v4 query lock unconditionally replaced the model's `find_documents` query
with the filler-stripped user message. A context-dependent follow-up such as
"Filtrera ner dokumenten" strips down to `"ner"`, which then became the search
query, discarding the model's well-formed phrase built from conversation
context.

The lock is now conditional: the user-message query replaces the model's query
only when it names a document type (`type_from_user_phrase`). The stated
purpose — preventing a channel model from rewriting a Swedish type label into
an English phrase that misses the taxonomy — is preserved, and the mode lock
is unchanged. All 50 gold cases name a type in the message, so the frozen
baseline is unaffected. See `apply_intent_to_find_arguments` in
`app/services/workspace_intent.py`.

The query-side type matcher now shares the ingest classifier's synonym lexicon
(`TYPE_NEEDLES` in `app/services/document_find/taxonomy.py`): phrases such as
`andrahandsuthyrning`, `arrendeavtal`, `lägenhetsarrende`, `ramavtal` and `NDA`
map to their document type deterministically, and a pure synonym query skips
the embedding and hits the category index directly (`_content_remainder` in
`app/services/document_find/tool.py`).

## Presentation gate removal (new contract)

The deterministic `IntentDecision.presentation` gate is removed. The
`presentation` field and every consumer of it — `presentation_tools_allowed`,
`filter_specs_for_intent`, `allows_gallery`, and `_drop_find_after_lookup` —
are gone. The contract is now:

- `find_documents`, `get_workspace_context`, `show_document` and
  `show_document_set` always stay in the model's tool catalog. Intent no
  longer removes presentation tools.
- Presentation calls are always delivered. `publish` and
  `deliver_client_tools` no longer drop `show_document`/`show_document_set`.
- The single-file automatic open is no longer gated; the multi-document
  gallery still wins over the single-file heuristic.
- `IntentDecision` now carries only `operation`, `scope` and `query`, which
  still lock `find_documents` mode/selection and query.

The model + tool descriptions decide *whether* to present. "Visa inget
galleri" / "svara bara hur många" remain instructions in the user message,
not a system suppression. **Consequently "zero false automatic galleries" is
a model-behaviour property, not a system guarantee.**

The v1–v4 frozen baselines above predate this change and are historical:
they measured the gate, not the new contract. `GoldCase.expected_gallery`
therefore means "the case instructs the model not to show", not "the system
must suppress the gallery". The remaining single-language coupling is
`operation`/`query` (Swedish regex + taxonomy labels), which must become
model-driven before a multi-language rollout.
