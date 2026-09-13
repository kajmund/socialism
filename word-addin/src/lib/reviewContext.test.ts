import { describe, expect, it } from "vitest"

import type { DocumentIntentInterview, LatestWordJob } from "./types"
import {
  interviewDraftLocaleMismatch,
  localeForReview,
  reusedIntentPayload,
  savedReviewContext,
  shouldGenerateIntentInterview,
} from "./reviewContext"

const interview: DocumentIntentInterview = {
  document_type: "contract",
  questions: [
    {
      id: "party",
      text: "Vilken sida företräder du?",
      type: "single_choice",
      options: [
        { value: "supplier", label: "Leverantör" },
        { value: "buyer", label: "Köpare" },
      ],
      required: true,
      rationale: "Styr perspektivet.",
    },
  ],
}

const answers = [{ question_id: "party", selected_values: ["supplier"], free_text: null }]

function job(overrides: Partial<LatestWordJob> = {}): LatestWordJob {
  return {
    job_id: "job_1",
    status: "succeeded",
    actions: [],
    review_context: {
      locale: "sv",
      review_intent: "Leverantörsperspektiv",
      intent_interview: interview,
      intent_answers: answers,
    },
    ...overrides,
  }
}

describe("savedReviewContext", () => {
  it("returns a completed interview from the latest job", () => {
    const context = savedReviewContext(job())
    expect(context?.intent_interview?.document_type).toBe("contract")
    expect(context?.intent_answers).toEqual(answers)
  })

  it("rejects missing or incomplete interviews", () => {
    expect(savedReviewContext(null)).toBeNull()
    expect(savedReviewContext(job({ review_context: null }))).toBeNull()
    expect(
      savedReviewContext(
        job({
          review_context: {
            locale: "sv",
            review_intent: "",
            intent_interview: interview,
            intent_answers: [],
          },
        }),
      ),
    ).toBeNull()
  })
})

describe("shouldGenerateIntentInterview", () => {
  it("reuses a valid same-locale context instead of generating again", () => {
    const context = savedReviewContext(job())
    expect(
      shouldGenerateIntentInterview({
        context,
        locale: "sv",
        resetRequested: false,
      }),
    ).toBe(false)
  })

  it("generates again when the user resets intent or switches language", () => {
    const context = savedReviewContext(job())
    expect(
      shouldGenerateIntentInterview({
        context,
        locale: "sv",
        resetRequested: true,
      }),
    ).toBe(true)
    expect(
      shouldGenerateIntentInterview({
        context,
        locale: "en",
        resetRequested: false,
      }),
    ).toBe(true)
    expect(
      shouldGenerateIntentInterview({
        context: null,
        locale: "sv",
        resetRequested: false,
      }),
    ).toBe(true)
  })
})

describe("reusedIntentPayload", () => {
  it("carries interview answers and free review intent", () => {
    const context = savedReviewContext(job())
    expect(context).not.toBeNull()
    expect(reusedIntentPayload(context!)).toEqual({
      interview,
      answers,
      reviewIntent: "Leverantörsperspektiv",
    })
  })
})

describe("localeForReview", () => {
  it("maps the add-in locale to the job contract", () => {
    expect(localeForReview("en")).toBe("en")
    expect(localeForReview("sv")).toBe("sv")
    expect(localeForReview("nb")).toBe("sv")
  })
})

describe("interviewDraftLocaleMismatch", () => {
  it("invalidates a draft generated in another language", () => {
    expect(
      interviewDraftLocaleMismatch({ draftLocale: "sv", locale: "en" }),
    ).toBe(true)
    expect(
      interviewDraftLocaleMismatch({ draftLocale: "sv", locale: "sv" }),
    ).toBe(false)
    expect(
      interviewDraftLocaleMismatch({ draftLocale: undefined, locale: "sv" }),
    ).toBe(true)
  })
})
