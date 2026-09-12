import { describe, expect, it } from "vitest"

import { ApiError } from "./http"
import {
  InvalidIntentInterviewError,
  answersReady,
  isIntentInterviewInvalidError,
  isQuestionAnswered,
  normalizeIntentAnswers,
  parseIntentInterview,
  setFreeTextAnswer,
  setSingleChoice,
  toggleMultiChoice,
} from "./intentInterview"
import type { DocumentIntentInterview, IntentQuestion } from "./types"

function interview(
  questions: IntentQuestion[],
): DocumentIntentInterview {
  return { document_type: "report", questions }
}

const party: IntentQuestion = {
  id: "party",
  text: "Vilken part företräder du?",
  type: "single_choice",
  required: true,
  rationale: "Partsställning ändrar analysen.",
  options: [
    { value: "buyer", label: "Köpare" },
    { value: "seller", label: "Säljare" },
  ],
}

const risks: IntentQuestion = {
  id: "risks",
  text: "Vilka risker ska prioriteras?",
  type: "multi_choice",
  required: true,
  rationale: "Prioritering styr kommentarbudget.",
  options: [
    { value: "legal", label: "Juridik" },
    { value: "finance", label: "Ekonomi" },
  ],
}

describe("parseIntentInterview", () => {
  it("fails closed on unknown question types", () => {
    expect(() =>
      parseIntentInterview({
        document_type: "cv",
        questions: [{ ...party, type: "ranked_choice" }],
      }),
    ).toThrow(InvalidIntentInterviewError)
  })

  it("fails closed on more than five questions", () => {
    expect(() =>
      parseIntentInterview({
        document_type: "cv",
        questions: Array.from({ length: 6 }, (_, index) => ({
          ...party,
          id: `q${index}`,
        })),
      }),
    ).toThrow(InvalidIntentInterviewError)
  })

  it("accepts a valid generated interview", () => {
    const parsed = parseIntentInterview({
      document_type: "cv",
      questions: [party],
    })
    expect(parsed.document_type).toBe("cv")
    expect(parsed.questions).toHaveLength(1)
  })
})

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

describe("intent answers", () => {
  it("does not treat interview answers as review intent text", () => {
    const answers = setSingleChoice([], "party", "buyer")
    expect(answers[0]?.selected_values).toEqual(["buyer"])
    expect(JSON.stringify(answers)).not.toContain("Köpare")
  })

  it("requires all required questions before start", () => {
    const draft = interview([party, risks])
    const afterParty = setSingleChoice([], "party", "buyer")
    expect(answersReady(draft, afterParty)).toBe(false)
    const afterRisks = toggleMultiChoice(afterParty, "risks", "legal")
    expect(answersReady(draft, afterRisks)).toBe(true)
    expect(isQuestionAnswered(risks, afterRisks[1])).toBe(true)
  })

  it("keeps spaces while editing free text and trims only on submit", () => {
    const typing = setFreeTextAnswer([], "note", "Fokusera ")
    expect(typing).toEqual([
      {
        question_id: "note",
        selected_values: [],
        free_text: "Fokusera ",
      },
    ])
    expect(isQuestionAnswered({ ...party, id: "note", type: "free_text", options: [] }, typing[0])).toBe(
      true,
    )
    expect(normalizeIntentAnswers(typing)).toEqual([
      {
        question_id: "note",
        selected_values: [],
        free_text: "Fokusera",
      },
    ])
    expect(setFreeTextAnswer([], "note", "")).toEqual([])
    expect(normalizeIntentAnswers(setFreeTextAnswer([], "note", "   "))).toEqual([])
  })

  it("removes an optional multi-choice answer when the last option is unchecked", () => {
    const optionalRisks = { ...risks, required: false }
    const selected = toggleMultiChoice([], "risks", "legal")
    expect(answersReady(interview([optionalRisks]), selected)).toBe(true)
    const cleared = toggleMultiChoice(selected, "risks", "legal")
    expect(cleared).toEqual([])
    expect(normalizeIntentAnswers(cleared)).toEqual([])
  })
})
