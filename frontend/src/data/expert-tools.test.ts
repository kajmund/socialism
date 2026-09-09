import { describe, expect, it } from "vitest"
import {
  DEFAULT_EXPERT_TOOLS,
  normalizeExpertTools,
  normalizePersonaTools,
} from "./expert-tools"

describe("normalizeExpertTools", () => {
  it("defaults missing tools to the full catalog", () => {
    expect(normalizeExpertTools(null)).toEqual([...DEFAULT_EXPERT_TOOLS])
  })

  it("keeps an explicit empty selection", () => {
    expect(normalizeExpertTools([])).toEqual([])
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
