import { describe, expect, it } from "vitest"
import { smeProductAllowsPath } from "./smePaths"

describe("smeProductAllowsPath", () => {
  it("keeps SME users on the messenger shell", () => {
    expect(smeProductAllowsPath("/jobs")).toBe(false)
    expect(smeProductAllowsPath("/profil")).toBe(false)
    expect(smeProductAllowsPath("/tools")).toBe(false)
    expect(smeProductAllowsPath("/personas")).toBe(false)
  })
})
