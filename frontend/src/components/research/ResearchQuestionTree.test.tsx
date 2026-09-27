import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { ResearchOverviewQuestionNode, ResearchProgressEvent } from "@/api/execution"
import { LocaleProvider } from "@/i18n"

import { ResearchQuestionTree } from "./ResearchQuestionTree"

const nodes: ResearchOverviewQuestionNode[] = [
  {
    id: "root", attempt_id: "a", parent_question_id: null, question: "Root", depth: 0,
    created_from: "root", phase: "completed", atomicity: "pending",
    researchability: "researchable", decomposability: "decomposable",
    completeness: "answered_with_gaps", research_need_id: null,
    current_answer: { id: "answer-root", version: 2, status: "answered_with_gaps", text: "Current root answer", child_answer_ids: ["answer-child"], evidence_item_ids: [] },
    sources: [],
  },
  {
    id: "child", attempt_id: "a", parent_question_id: "root", question: "Gap child", depth: 1,
    created_from: "gap", phase: "ready", atomicity: "pending",
    researchability: "researchable", decomposability: "not_decomposable", completeness: null,
    research_need_id: "need-child", current_answer: null,
    sources: [{ id: "evidence-1", passage_id: null, domain_result_id: null, raw_source_id: null, analysis: null, research_need_ids: ["need-child"], status: "found", title: "NJA 1983 s. 332", excerpt: "Oskäligt villkor", locator: null, source_url: "https://lagen.nu/dom/nja/1983s332", source_type: "swedish_case_law", provider: "lagen.nu" }],
  },
]

describe("ResearchQuestionTree", () => {
  it("renders the current answer, gap marker, and nested child", () => {
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionTree nodes={nodes} /></LocaleProvider>)
    expect(html).toContain("Current root answer")
    expect(html).toContain("Fråga från kunskapslucka")
    expect(html).toContain("Gap child")
    expect(html).not.toContain("answer-root")
    expect(html).toContain("Inget svar ännu.")
    expect(html).toContain("NJA 1983 s. 332")
    expect(html).toContain("Oskäligt villkor")
    expect(html.indexOf("NJA 1983 s. 332")).toBeLessThan(html.indexOf("Inget svar ännu."))
  })

  it("shows an execution failure instead of a missing answer", () => {
    const failed = nodes.map((node) => node.id === "child" ? { ...node, phase: "failed" } : node)
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionTree nodes={failed} /></LocaleProvider>)
    expect(html).toContain("Researchen kraschade innan svaret sparades.")
    expect(html).toContain("Tekniskt misslyckad")
  })

  it("describes a depth guardrail as unfinished, not a technical failure", () => {
    const limited = nodes.map((node) => node.id === "child"
      ? { ...node, phase: "unresolved", atomicity: "composite", completeness: null }
      : node)
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionTree nodes={limited} /></LocaleProvider>)
    expect(html).toContain("Ej färdigundersökt")
    expect(html).toContain("Current root answer")
    expect(html).not.toContain("kraschade")
    expect(html).not.toContain("Tekniskt misslyckad")
  })

  it("shows found evidence on the question instead of still searching", () => {
    const searching = nodes.map((node) => node.id === "child" ? { ...node, phase: "researching" } : node)
    const events: ResearchProgressEvent[] = [
      { id: "e1", attempt_id: "a", sequence: 1, event_type: "question_research_started", occurred_at: "2026-09-27T10:00:00Z", payload: { question_id: "child" } },
      { id: "e2", attempt_id: "a", sequence: 2, event_type: "evidence_found", occurred_at: "2026-09-27T10:01:00Z", payload: { question_id: "child" } },
      { id: "e3", attempt_id: "a", sequence: 3, event_type: "evidence_found", occurred_at: "2026-09-27T10:02:00Z", payload: { research_need_id: "need-child" } },
      { id: "e4", attempt_id: "a", sequence: 4, event_type: "need_running", occurred_at: "2026-09-27T10:03:00Z", payload: { question_id: "child" } },
    ]
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionTree nodes={searching} events={events} /></LocaleProvider>)
    const foundAt = html.indexOf("Hittade 2 evidens")
    const searchingAt = html.indexOf("Söker evidens")
    expect(foundAt).toBeGreaterThan(-1)
    expect(searchingAt).toBeGreaterThan(foundAt)
    expect(html).toContain("Händelser")
    expect(html).not.toContain("research_need_id")
    expect(html).not.toContain("question_id")
  })

  it("describes decomposition exhaustion as researching the whole question", () => {
    const whole = nodes.map((node) => node.id === "child" ? { ...node, phase: "ready", created_from: "decomposition" } : node)
    const events: ResearchProgressEvent[] = [
      {
        id: "e1",
        attempt_id: "a",
        sequence: 1,
        event_type: "question_decomposed",
        occurred_at: "2026-09-27T10:00:00Z",
        payload: {
          question_id: "child",
          decision: "rejected",
          decomposition_result: "exhausted",
          fallback: "best_effort_retrieval",
        },
      },
    ]
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionTree nodes={whole} events={events} /></LocaleProvider>)
    expect(html).toContain("Kunde inte dela upp frågan meningsfullt")
    expect(html).toContain("Forskar frågan som helhet")
    expect(html).not.toContain("Tekniskt fel")
    expect(html).not.toContain("Tekniskt misslyckad")
  })

  it("describes a stopped branch as not required", () => {
    const stopped = nodes.map((node) => node.id === "child" ? { ...node, phase: "not_required" } : node)
    const html = renderToStaticMarkup(<LocaleProvider><ResearchQuestionTree nodes={stopped} /></LocaleProvider>)
    expect(html).toContain("Behövde inte undersökas vidare")
    expect(html).toContain("Current root answer")
    expect(html).not.toContain("kraschade")
  })
})
