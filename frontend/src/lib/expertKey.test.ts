import { describe, expect, it } from "vitest"
import { expertRoleKey, uniqueExpertKey } from "@/lib/expertKey"

describe("expertRoleKey", () => {
  it("slugs the display name like the backend", () => {
    expect(expertRoleKey("IT-revisor")).toBe("it_revisor")
    expect(expertRoleKey("Finansiell analytiker")).toBe("finansiell_analytiker")
    expect(expertRoleKey("  ")).toBe("expert")
  })
})

describe("uniqueExpertKey", () => {
  it("returns the base slug when free", () => {
    expect(uniqueExpertKey("Jurist", ["spinndoctor"])).toBe("jurist")
  })

  it("suffixes before create when the slug is taken", () => {
    expect(uniqueExpertKey("Jurist", ["jurist", "jurist_2"])).toBe("jurist_3")
  })

  it("avoids colliding with keys assigned in the same batch", () => {
    const taken = new Set(["marknadsanalytiker"])
    const first = uniqueExpertKey("Marknadsanalytiker", taken)
    taken.add(first)
    const second = uniqueExpertKey("Marknadsanalytiker", taken)
    expect(first).toBe("marknadsanalytiker_2")
    expect(second).toBe("marknadsanalytiker_3")
  })
})
