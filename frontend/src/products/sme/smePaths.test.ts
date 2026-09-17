import { describe, expect, it } from "vitest"
import { smeProductAllowsPath } from "./smePaths"

describe("smeProductAllowsPath", () => {
  it("keeps /jobs reachable for SME customers", () => {
    expect(smeProductAllowsPath("/jobs")).toBe(true)
    expect(smeProductAllowsPath("/jobs/")).toBe(true)
  })

  it("does not open the rest of the admin tree", () => {
    expect(smeProductAllowsPath("/")).toBe(false)
    expect(smeProductAllowsPath("/tools")).toBe(false)
    expect(smeProductAllowsPath("/personas")).toBe(false)
  })
})
