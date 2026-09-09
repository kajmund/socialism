import { describe, expect, it } from "vitest"
import type { Kund } from "@/api/kunder"
import { kunderForScope, uniqueModuleIds } from "@/modules/useKundModules"

function kund(slug: string, available_modules: string[], id: number): Kund {
  return { id, name: slug, slug, available_modules, projekt: [] }
}

const os = kund("devbrains", ["politik", "expertgranskning"], 1)
const bolag = kund("bolag-demo", ["dd"], 2)

describe("kunderForScope", () => {
  it("keeps the admin union when scope is the main shell", () => {
    expect(kunderForScope([os, bolag], "admin", "admin")).toEqual([os, bolag])
  })

  it("uses only the bolag kund on bolag surfaces, even for admin", () => {
    expect(kunderForScope([os, bolag], "admin", "bolag")).toEqual([bolag])
  })

  it("uses the bolag kund for bolag role regardless of scope", () => {
    expect(kunderForScope([os, bolag], "bolag", "admin")).toEqual([bolag])
    expect(kunderForScope([os, bolag], "bolag", "bolag")).toEqual([bolag])
  })

  it("uses the OS kund for user role", () => {
    expect(kunderForScope([os, bolag], "user", "admin")).toEqual([os])
  })
})

describe("uniqueModuleIds", () => {
  it("does not include modules the bolag kund lacks", () => {
    expect(uniqueModuleIds([bolag])).toEqual(["dd"])
  })
})
