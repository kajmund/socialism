import { describe, expect, it } from "vitest"

import { ApiError } from "@/lib/api"

import { fixtureAttemptA, fixtureAttemptB } from "./executionFixtures"
import { loadStateFromError, shouldFetchEvidence, shouldFetchResult } from "./fetchPolicy"

describe("execution fetch policy", () => {
  it("does not fetch evidence or result when the attempt has none", () => {
    expect(shouldFetchEvidence(fixtureAttemptB)).toBe(false)
    expect(shouldFetchResult(fixtureAttemptB)).toBe(false)
  })

  it("fetches evidence and result when the attempt has them", () => {
    expect(shouldFetchEvidence(fixtureAttemptA)).toBe(true)
    expect(shouldFetchResult(fixtureAttemptA)).toBe(true)
  })

  it("maps 403 and 404 to dedicated page states", () => {
    expect(loadStateFromError(new ApiError("nope", { status: 403 }))).toBe("forbidden")
    expect(loadStateFromError(new ApiError("missing", { status: 404 }))).toBe("not_found")
    expect(loadStateFromError(new ApiError("boom", { status: 500 }))).toBe("error")
  })
})
