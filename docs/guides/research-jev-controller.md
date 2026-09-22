# Research Jev fast controller

Jev is a bounded System One control layer in front of the expensive research
assessor and completeness reviewer. It does not replace retrieval, planning,
follow-up question writing, legal extraction, or expert reasoning.

Default: **off**. When enabled without `TYPESAFE_API_KEY`, it stays off. When
enabled with a key, the default mode is **shadow**: Jev runs, the current LLM
path still runs, and ELK records the comparison.

## Insertion points

1. Programmatic assessment/completeness (unchanged).
2. `GatedResearchAssessor` / `GatedResearchCompletenessReviewer` in
   `app/services/research/fast_gate.py`.
3. Wired only from `build_llm_research_assessor` and
   `build_llm_research_completeness_reviewer`. Direct `LlmResearchAssessor`
   construction in tests is unchanged.
4. `execute_attempt_research` binds correlation IDs and emits
   `research.execution.summary`.

## Config

See `docs/guides/backend-setup.md` for `RESEARCH_JEV_*`. Jev research settings
are separate from Auto prompt-selection (`JEV_*`).

## ELK events

All events use `event.dataset = socialism.research` and structured fields, not
message-string parsing.

| Event | When |
| --- | --- |
| `research.jev.assessment.started` / `.completed` / `.failed` | Assessor gate |
| `research.jev.completeness.started` / `.completed` / `.failed` | Completeness gate |
| `research.jev.evidence_scored` | Per-item shadow screen |
| `research.jev.shadow_comparison` | After the current LLM decision exists |
| `research.jev.short_circuit` | Active mode actually skipped an LLM call |
| `research.execution.summary` | Attempt research finished |

Correlation fields when known: `run.id`, `attempt.id`, `research.question_id`,
`research.child_attempt_id`, `research.need_id`, `customer.id`,
`research.module`, `research.wave_number`, `trace.id`.

Jev errors are categorized (`timeout`, `auth`, `rate_limit`, `invalid_response`,
`schema_validation`, `transport`, `unknown`) and always fall back to the current
LLM path.

Info events log IDs, hashes, counts, source types, probabilities, and latency.
They do not log full evidence, document text, or prompts.
