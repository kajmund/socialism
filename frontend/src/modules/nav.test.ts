import { describe, expect, it } from "vitest"
import { buildSidebarNav } from "@/modules/nav"

describe("buildSidebarNav", () => {
  it("includes expertgranskning for admin even when no kund has it", () => {
    const sections = buildSidebarNav({ moduleIds: ["politik"], showTools: true })
    expect(sections.map((section) => section.id)).toContain("expertgranskning")
    const item = sections.find((section) => section.id === "expertgranskning")?.items[0]
    expect(item?.to).toBe("/expertgranskning")
  })

  it("does not inject expertgranskning for non-admin shells", () => {
    const sections = buildSidebarNav({ moduleIds: ["dd"], showTools: false })
    expect(sections.map((section) => section.id)).not.toContain("expertgranskning")
  })
})
