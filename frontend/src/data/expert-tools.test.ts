import { describe, expect, it } from "vitest"
import {
  DEFAULT_EXPERT_TOOLS,
  normalizeExpertTools,
  normalizePersonaTools,
  selectAllExpertTools,
  toggleExpertTool,
} from "./expert-tools"

describe("normalizeExpertTools", () => {
  it("defaults missing tools to the full catalog", () => {
    expect(normalizeExpertTools(null)).toEqual([...DEFAULT_EXPERT_TOOLS])
    expect(DEFAULT_EXPERT_TOOLS).toContain("start_research")
  })

  it("keeps an explicit empty selection", () => {
    expect(normalizeExpertTools([])).toEqual([])
  })

  it("keeps start_research when other catalog tools are selected", () => {
    expect(normalizeExpertTools(["start_research", "search_wiki"])).toEqual([
      "start_research",
      "search_wiki",
    ])
  })
})

describe("normalizePersonaTools", () => {
  it("defaults missing tools to none", () => {
    expect(normalizePersonaTools(null)).toEqual([])
  })

  it("keeps selected catalog tools in order", () => {
    expect(normalizePersonaTools(["search_wiki", "search_wiki", "lookup_company"])).toEqual([
      "search_wiki",
      "lookup_company",
    ])
  })
})

describe("expert tool selection", () => {
  it("keeps start_research when another tool is toggled", () => {
    const current = ["search_wiki", "start_research"] as const
    expect(toggleExpertTool(current, "search_wiki", false)).toEqual(["start_research"])
    expect(toggleExpertTool(["start_research"], "lookup_company", true)).toEqual([
      "lookup_company",
      "start_research",
    ])
  })

  it("includes start_research in select-all and can clear it explicitly", () => {
    expect(selectAllExpertTools(true)).toContain("start_research")
    expect(selectAllExpertTools(false)).toEqual([])
  })
})
