import { describe, expect, it } from "vitest"
import { formatSimilarity } from "./scoreFormat"

describe("formatSimilarity", () => {
  it("shows cosine similarity, not a probability percent", () => {
    expect(formatSimilarity(0.82, "sv-SE")).not.toContain("%")
    expect(formatSimilarity(0.82, "en-US")).toBe("0.82")
    expect(formatSimilarity(null, "sv-SE")).toBe("—")
  })
})
