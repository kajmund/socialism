# Reuse before new (mandatory)

This is a permanent coding-agent standard. It applies to every spec,
experiment, and implementation in this repo.

Linked from [AGENTS.md](../../AGENTS.md) and [backend/AGENTS.md](../../backend/AGENTS.md).

## Required order

1. **Inventory** existing code, tests, interfaces, workflows, and related
   patterns for the job.
2. **Write a reuse-vs-new matrix** before adding a class, module,
   workflow, or runner: existing counterpart, reuse / extend / new,
   justification if new.
3. **Default to extending** existing primitives. New frameworks,
   wrappers, parallel runners, or duplicated domain models need an
   explicit documented reason.
4. **Prove the reused path** with an integration test that invokes the
   existing primitive (not a lookalike).
5. **Keep mocked benchmarks separate** from live model measurements.
   Do not present scripted scores as model quality.

## Default primitives

| Concern | Reuse this |
| ------- | ---------- |
| Orchestration | `app.swe.runtime.WorkflowRunner` / `run_workflow` / `WorkflowResources` (see `research/swe_bridge.py`) |
| Jev decisions | `app.swe.providers.make_jev_provider`, `research/fast_controller.py` (`ASSESSMENT_QUESTIONS`, `classify_research_decision`, telemetry) |
| Passage screen | `research/evidence_screen.py` (`EVIDENCE_SCREEN_QUESTIONS`, `EvidenceJevScores`) |
| Evidence quality | `research/quality.py` (`EvidenceQualityDraft`, `independence_key`) |
| Assessment contracts | `research/assessment.py` (`AssessableEvidence`, `ResearchAssessmentDraft`, `sanitize_assessment_draft`, `group_evidence_for_review`) |
| Loop lifecycle | `research/loop_control.py` + `loop_decision.py` (assessment → follow-up → completeness). Do not invent a second lifecycle. |

## Anti-patterns

- Compiling an SWD document and then running a separate Python loop
- A second evidence/assessment model next to `AssessableEvidence`
- Treating five copies of one `independence_key` as five sources
- Equating local sufficiency with global completeness
- Claiming scripted Jev/Cerebras numbers as live model quality
- Adding a parallel orchestration framework
