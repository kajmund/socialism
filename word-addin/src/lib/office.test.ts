import { describe, expect, it } from "vitest"

import {
  findRewriteTargetIndex,
  normalizeParagraphText,
  paragraphTextMatchesReviewed,
} from "./office"

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

describe("findRewriteTargetIndex", () => {
  const paragraphs = ["Rubrik", "Hej stycke.", "Nästa stycke."]

  it("keeps the requested index when that paragraph still matches", () => {
    expect(findRewriteTargetIndex(paragraphs, 1, "Hej stycke.")).toBe(1)
  })

  it("relocates a unique reviewed paragraph after an insert above it", () => {
    expect(
      findRewriteTargetIndex(
        ["Ny ingress", "Rubrik", "Hej stycke.", "Nästa stycke."],
        1,
        "Hej stycke.",
      ),
    ).toBe(2)
  })

  it("skips when the reviewed text is gone or no longer unique", () => {
    expect(findRewriteTargetIndex(paragraphs, 1, "Borta.")).toBeNull()
    expect(
      findRewriteTargetIndex(["Hej stycke.", "Hej stycke."], 0, "Hej stycke.\r"),
    ).toBe(0)
    expect(findRewriteTargetIndex(["Hej stycke.", "Hej stycke."], 3, "Hej stycke.")).toBeNull()
    expect(findRewriteTargetIndex(paragraphs, 1, null)).toBeNull()
  })
})
