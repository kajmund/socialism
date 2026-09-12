import { describe, expect, it } from "vitest"
import type { AuthUser } from "@/lib/auth"
import { reportModulesForUser } from "@/lib/report-modules"

function user(role: AuthUser["role"], modules: string[]): AuthUser {
  return {
    id: "u1",
    username: "a@b.se",
    email: "a@b.se",
    role,
    modules,
    kundSlug: role === "bolag" ? "bolag-demo" : "devbrains",
    kundId: role === "bolag" ? 2 : 1,
  }
}

describe("reportModulesForUser", () => {
  it("does not flash OS module tabs on bolag surfaces for admin", () => {
    expect(reportModulesForUser(user("admin", ["politik", "dd", "expertgranskning"]), "bolag")).toEqual([
      "dd",
    ])
  })

  it("uses the bolag account modules on bolag surfaces", () => {
    expect(reportModulesForUser(user("bolag", ["dd", "expertgranskning"]), "bolag")).toEqual([
      "dd",
      "expertgranskning",
    ])
  })

  it("keeps the declared union on the main shell", () => {
    expect(reportModulesForUser(user("admin", ["politik", "dd"]))).toEqual(["politik", "dd"])
  })
})
