import { describe, expect, it } from "vitest"

import { ApiError } from "@/lib/http"

import { fixtureAttemptA, fixtureAttemptCreated } from "./executionFixtures"
import {
  isExpectedMissing,
  loadStateFromError,
  sectionErrorMessage,
  shouldFetchEvidence,
  shouldFetchResult,
} from "./fetchPolicy"

describe("execution fetch policy", () => {
  it("does not fetch evidence or result when the attempt has none", () => {
    expect(shouldFetchEvidence(fixtureAttemptCreated)).toBe(false)
    expect(shouldFetchResult(fixtureAttemptCreated)).toBe(false)
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

  it("treats only 404 as an expected empty evidence or result", () => {
    expect(isExpectedMissing(new ApiError("gone", { status: 404 }))).toBe(true)
    expect(isExpectedMissing(new ApiError("denied", { status: 403 }))).toBe(false)
    expect(isExpectedMissing(new ApiError("boom", { status: 500 }))).toBe(false)
    expect(isExpectedMissing(new ApiError("offline", { isNetworkError: true }))).toBe(false)
  })

  it("keeps the API message for a section error", () => {
    expect(sectionErrorMessage(new ApiError("kund_access_denied", { status: 403 }), "fallback")).toBe(
      "kund_access_denied",
    )
    expect(sectionErrorMessage(new Error(""), "fallback")).toBe("fallback")
  })
})
