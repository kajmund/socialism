# Evidence sufficiency experiment — reuse audit

Mandatory matrix for PR #422. Inventory was taken against `main` primitives
listed in the follow-up spec. Production `LlmResearchAssessor` is unchanged.

Policy: [reuse-before-new.md](reuse-before-new.md).

## Inventory (existing)

| Primitive | Path | Role |
| --------- | ---- | ---- |
| SWE runner | `app/swe/runtime.py` | `WorkflowRunner`, `WorkflowResources`, cancel, concurrency, resume |
| Research SWE pattern | `app/services/research/swe_bridge.py` | `map` of children, handlers on a loop object, expression route |
| Jev provider | `app/swe/providers.py` | System One provider + `classify_research_decision` |
| Fast controller | `app/services/research/fast_controller.py` | `ASSESSMENT_QUESTIONS`, NOUL, confidence, telemetry, errors |
| Evidence screen | `app/services/research/evidence_screen.py` | Passage-level NOUL + `EvidenceJevScores` |
| Quality | `app/services/research/quality.py` | `EvidenceQualityDraft`, `independence_key` |
| Assessment | `app/services/research/assessment.py` | `AssessableEvidence`, grouping, sanitize, programmatic gate |
| Loop | `app/services/research/loop_control.py` + `loop_decision.py` | assess → follow-up → completeness |

## Reuse-vs-new matrix

| New unit | Existing counterpart | Decision | Justification if new | Integration test |
| -------- | -------------------- | -------- | -------------------- | ---------------- |
| `SufficiencyLoop` | `SweResearchLoop` | **Extend pattern** | Same handler-object + `WorkflowRunner` + `map` + expression route. Not a second engine. | `test_sufficiency_runs_through_swe_native` |
| `SUFFICIENCY_WORKFLOW` | `swe_bridge._workflow` | **Reuse SWE nodes** | `task` / `map` / `decision(expression)` / `end` only | same; events include `BranchSpawned`, `DecisionTaken` |
| Passage NOUL | `EVIDENCE_SCREEN_QUESTIONS` + `EvidenceJevScores` | **Reuse** | No new verdict enum | `test_passage_eval_uses_evidence_screen_questions` |
| Need/route NOUL | `ASSESSMENT_QUESTIONS` + `classify_research_decision` | **Reuse** | Map sufficient/insufficient/uncertain onto FINISH / RUN_SUBWORKFLOW / ESCALATE / UNCERTAIN with deterministic validation | `test_route_uses_classify_research_decision` |
| Independence | `quality.independence_key` | **Reuse** | Duplicates collapse; not a new identity | `test_duplicate_sources_are_one_independence_key` |
| Draft output | `ResearchAssessmentDraft` + `sanitize_assessment_draft` | **Reuse** | No competing result model | `test_sanitize_blocks_invented_ids` (existing sanitizer) |
| Grouping | `group_evidence_for_review` | **Reuse** | Before segmentation | `test_group_then_segment_keeps_need_lineage` |
| Quality flags | `EvidenceQualityDraft` | **Reuse** | Sufficiency reads authority/relevance/independence | `test_quality_independence_blocks_false_corroboration` |
| Loop meanings | `decide_after_assessment` | **Reuse / do not replace** | Experiment is only a `ResearchAssessor`. Follow-up and completeness stay in `loop_control`. | `test_experiment_does_not_import_loop_control` (no second lifecycle) |
| `EvidencePassage` | none (spans only) | **New** | Assessment items have one excerpt; PR #420 trims it. Spans are offsets into that excerpt, not a new evidence entity. | `test_segment_text_covers_every_character` |
| `EvidenceObligation` | `ResearchNeed.source_types` / `capabilities` | **Derive, thin record** | Needs have no explicit coverage rows. Obligations are projected from `source_types` + `capabilities`. Empty `source_types` ⇒ unknown ⇒ UNCERTAIN. | `test_unknown_source_types_are_uncertain` |
| `ExperimentReport` | `ResearchAssessmentDraft` | **New wrapper** | Adds SWE event/metrics fields the draft cannot hold. Draft remains the product contract. | golden + SWE tests |
| `GateInputs` | quality_gate kwargs | **Thin record** | Packs coverage/budget inputs so the gate stays within argument limits. Not a product model. | `test_quality_gate_*` |
| Scripted Jev | live `HttpJevSystemOne` | **Test double only** | Unit tests. Live path is separate and reports unavailable when keys are missing. | `test_live_measurement_is_explicitly_unavailable` |
| Parallel Python assessor loop | `run_experiment` pre-audit | **Removed** | Execution is `WorkflowRunner.run` only | `test_run_experiment_calls_workflow_runner` |

## Removed / not added

- Custom `SUPPORTED`/`UNSUPPORTED` choice schema (replaced by existing NOUL screens)
- `jev_requires_narrative=any(needs_narrative)`
- `if supporting: sufficient=True`
- Contradiction ⇒ final insufficient
- A second research wave loop
- A new orchestration framework
- Fabricated live Cerebras/Jev scores (no `TYPESAFE_API_KEY` / `CEREBRAS_API_KEY` in this environment)

## Production

`build_llm_research_assessor` / `LlmResearchAssessor` / `encode_assessment_input` unchanged.
