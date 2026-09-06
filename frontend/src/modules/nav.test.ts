import { describe, expect, it } from "vitest"
import { buildSidebarNav } from "@/modules/nav"

describe("buildSidebarNav", () => {
  it("includes expertgranskning for admin even when no kund has it", () => {
    const sections = buildSidebarNav({ moduleIds: ["politik"], showTools: true })
    expect(sections.map((section) => section.id)).toContain("expertgranskning")
    const item = sections.find((section) => section.id === "expertgranskning")?.items[0]
    expect(item?.to).toBe("/expertgranskning")
  })

  it("includes rattsunderlag for admin even when no kund has it", () => {
    const sections = buildSidebarNav({ moduleIds: ["politik"], showTools: true })
    expect(sections.map((section) => section.id)).toContain("rattsunderlag")
    const item = sections.find((section) => section.id === "rattsunderlag")?.items[0]
    expect(item?.to).toBe("/rattsunderlag")
  })

  it("does not inject expertgranskning for non-admin shells", () => {
    const sections = buildSidebarNav({ moduleIds: ["dd"], showTools: false })
    expect(sections.map((section) => section.id)).not.toContain("expertgranskning")
  })

  it("groups experts and expert panels under Experter", () => {
    const sections = buildSidebarNav({ moduleIds: ["dd"], showTools: false })
    const experts = sections.find((section) => section.id === "dd:bolag.nav.experter")
    expect(experts?.titleKey).toBe("bolag.nav.experter")
    expect(experts?.items.map((item) => item.key)).toEqual([
      "bolag.nav.experter",
      "bolag.nav.expertPanels",
    ])
    const dd = sections.find((section) => section.id === "dd")
    expect(dd?.titleKey).toBe("modules.dd.name")
    expect(dd?.items.map((item) => item.key)).toEqual(["bolag.nav.campaigns"])
    const ids = sections.map((section) => section.id)
    expect(ids.indexOf("dd:bolag.nav.experter")).toBe(ids.indexOf("shared") - 1)
    expect(ids.indexOf("dd")).toBeLessThan(ids.indexOf("dd:bolag.nav.experter"))
  })
})
