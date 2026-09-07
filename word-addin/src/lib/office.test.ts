import { describe, expect, it } from "vitest"

import { normalizeParagraphText, paragraphTextMatchesReviewed } from "./office"

describe("normalizeParagraphText", () => {
  it("strips carriage returns and surrounding space", () => {
    expect(normalizeParagraphText("  Hej\r\n ")).toBe("Hej")
  })
})

describe("paragraphTextMatchesReviewed", () => {
  it("matches after Word-style CR normalization", () => {
    expect(paragraphTextMatchesReviewed("Hej stycke.\r", "Hej stycke.")).toBe(true)
  })

  it("treats missing or blank reviewed text as a mismatch", () => {
    expect(paragraphTextMatchesReviewed("Hej stycke.", null)).toBe(false)
    expect(paragraphTextMatchesReviewed("Hej stycke.", "  ")).toBe(false)
    expect(paragraphTextMatchesReviewed("Hej stycke.", undefined)).toBe(false)
  })

  it("rejects a different current paragraph", () => {
    expect(paragraphTextMatchesReviewed("Annat stycke.", "Hej stycke.")).toBe(false)
  })
})
