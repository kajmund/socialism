import { describe, expect, it } from "vitest"
import { blockingDependencyCount } from "./researchStatus"

describe("research dependency presentation", () => {
  it("does not label answered or running questions as waiting", () => {
    for (const status of ["answered", "running", "insufficient"]) {
      expect(blockingDependencyCount({ status, blocking_dependency_ids: ["parent"] })).toBe(0)
    }
  })
  it("counts only explicitly blocking dependencies", () => {
    expect(blockingDependencyCount({ status: "waiting", blocking_dependency_ids: ["pending"] })).toBe(1)
    expect(blockingDependencyCount({ status: "waiting", blocking_dependency_ids: [] })).toBe(0)
  })
})
