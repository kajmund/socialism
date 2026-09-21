import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ResearchOverviewQuestion } from "@/api/execution"
import { LocaleProvider } from "@/i18n"

import { ResearchQuestionCard } from "./ResearchQuestionCard"

const question: ResearchOverviewQuestion = {
  id: "question-a", question: "Need A", specific_question: "Need A context",
  why_needed: "", status: "insufficient", raw_status: "completed", outcome_reason: null,
  origin: "initial", depth: 0, child_attempt_id: "attempt", child_attempt_status: "ready",
  dependency_ids: [], raised_by: [], assigned_to: null,
  sources: [{ id: "evidence-a", passage_id: null, domain_result_id: null, raw_source_id: null, analysis: null, research_need_ids: ["need-a"], status: "found", title: "Shared source", excerpt: null, locator: null, source_url: null, source_type: "swedish_law", provider: "lagen.nu" }],
  source_count: 1,
  need_assessment: { research_need_id: "need-a", sufficient: false, supporting_evidence_ids: ["evidence-a"], missing_or_weak: "Need A gap", contradictions: [], further_information: "Need A follow-up" },
}

describe("ResearchQuestionCard", () => {
  it("renders the need assessment and never repeats the plan assessment", () => {
    const withGlobal = {
      ...question,
      assessment_rationale: "GLOBAL PLAN RATIONALE",
      completeness_rationale: "GLOBAL COMPLETENESS RATIONALE",
    }
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionCard question={withGlobal} /></LocaleProvider>)
    expect(html).toContain("Need A gap")
    expect(html).toContain("Need A follow-up")
    expect(html).toContain("Shared source")
    expect(html).not.toContain("GLOBAL PLAN RATIONALE")
    expect(html).not.toContain("GLOBAL COMPLETENESS RATIONALE")
  })
})
