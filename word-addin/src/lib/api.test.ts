import { describe, expect, it } from "vitest"

import { ApiError } from "./http"
import { InvalidIntentInterviewError } from "./intentInterview"
import { isIntentInterviewInvalidError } from "./api"

describe("isIntentInterviewInvalidError", () => {
  it("maps backend intent_interview_invalid to the interview-invalid error", () => {
    expect(
      isIntentInterviewInvalidError(
        new ApiError("intent_interview_invalid", { status: 422 }),
      ),
    ).toBe(true)
    expect(isIntentInterviewInvalidError(new InvalidIntentInterviewError())).toBe(true)
    expect(isIntentInterviewInvalidError(new ApiError("other", { status: 422 }))).toBe(
      false,
    )
    expect(isIntentInterviewInvalidError(new Error("intent_interview_invalid"))).toBe(
      false,
    )
  })
})
