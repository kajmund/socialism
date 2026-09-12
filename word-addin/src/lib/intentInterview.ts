import {
  INTENT_QUESTION_TYPES,
  type DocumentIntentInterview,
  type IntentAnswer,
  type IntentOption,
  type IntentQuestion,
  type IntentQuestionType,
} from "@/lib/types"

export class InvalidIntentInterviewError extends Error {
  override name = "InvalidIntentInterviewError"
  constructor() {
    super("invalid_interview")
  }
}

const INTENT_ID_RE = /^[a-z][a-z0-9_]{0,63}$/
const MAX_QUESTIONS = 5

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
}

function isQuestionType(value: unknown): value is IntentQuestionType {
  return (
    typeof value === "string" &&
    (INTENT_QUESTION_TYPES as readonly string[]).includes(value)
  )
}

function parseOption(value: unknown): IntentOption {
  if (!isRecord(value) || typeof value.value !== "string" || typeof value.label !== "string") {
    throw new InvalidIntentInterviewError()
  }
  const slug = value.value.trim()
  const label = value.label.trim()
  if (!INTENT_ID_RE.test(slug) || !label) {
    throw new InvalidIntentInterviewError()
  }
  return { value: slug, label }
}

function parseQuestion(value: unknown): IntentQuestion {
  if (!isRecord(value) || !isQuestionType(value.type)) {
    throw new InvalidIntentInterviewError()
  }
  if (typeof value.id !== "string" || !INTENT_ID_RE.test(value.id.trim())) {
    throw new InvalidIntentInterviewError()
  }
  if (typeof value.text !== "string" || !value.text.trim()) {
    throw new InvalidIntentInterviewError()
  }
  if (typeof value.rationale !== "string" || !value.rationale.trim()) {
    throw new InvalidIntentInterviewError()
  }
  if (!Array.isArray(value.options)) {
    throw new InvalidIntentInterviewError()
  }
  const options = value.options.map(parseOption)
  const optionValues = options.map((option) => option.value)
  if (optionValues.length !== new Set(optionValues).size) {
    throw new InvalidIntentInterviewError()
  }
  switch (value.type) {
    case "free_text":
      if (options.length > 0) throw new InvalidIntentInterviewError()
      break
    case "single_choice":
    case "multi_choice":
      if (options.length < 2) throw new InvalidIntentInterviewError()
      break
    default: {
      const _exhaustive: never = value.type
      throw _exhaustive
    }
  }
  return {
    id: value.id.trim(),
    text: value.text.trim(),
    type: value.type,
    options,
    required: value.required !== false,
    rationale: value.rationale.trim(),
  }
}

export function parseIntentInterview(data: unknown): DocumentIntentInterview {
  if (!isRecord(data) || typeof data.document_type !== "string" || !data.document_type.trim()) {
    throw new InvalidIntentInterviewError()
  }
  if (!Array.isArray(data.questions) || data.questions.length > MAX_QUESTIONS) {
    throw new InvalidIntentInterviewError()
  }
  const questions = data.questions.map(parseQuestion)
  const ids = questions.map((question) => question.id)
  if (ids.length !== new Set(ids).size) {
    throw new InvalidIntentInterviewError()
  }
  return {
    document_type: data.document_type.trim(),
    questions,
  }
}

export function answerForQuestion(
  answers: IntentAnswer[],
  questionId: string,
): IntentAnswer | undefined {
  return answers.find((answer) => answer.question_id === questionId)
}

export function isQuestionAnswered(
  question: IntentQuestion,
  answer: IntentAnswer | undefined,
): boolean {
  if (!answer) return false
  switch (question.type) {
    case "single_choice":
      return answer.selected_values.length === 1
    case "multi_choice":
      return answer.selected_values.length > 0
    case "free_text":
      return Boolean(answer.free_text?.trim())
    default: {
      const _exhaustive: never = question.type
      return _exhaustive
    }
  }
}

export function answersReady(
  interview: DocumentIntentInterview,
  answers: IntentAnswer[],
): boolean {
  return interview.questions.every(
    (question) =>
      !question.required || isQuestionAnswered(question, answerForQuestion(answers, question.id)),
  )
}

function upsertAnswer(
  answers: IntentAnswer[],
  questionId: string,
  next: Omit<IntentAnswer, "question_id">,
): IntentAnswer[] {
  const row: IntentAnswer = { question_id: questionId, ...next }
  const index = answers.findIndex((answer) => answer.question_id === questionId)
  if (index < 0) return [...answers, row]
  return answers.map((answer, current) => (current === index ? row : answer))
}

export function setSingleChoice(
  answers: IntentAnswer[],
  questionId: string,
  value: string,
): IntentAnswer[] {
  return upsertAnswer(answers, questionId, {
    selected_values: [value],
    free_text: null,
  })
}

export function toggleMultiChoice(
  answers: IntentAnswer[],
  questionId: string,
  value: string,
): IntentAnswer[] {
  const current = answerForQuestion(answers, questionId)?.selected_values ?? []
  const selected = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value]
  return upsertAnswer(answers, questionId, {
    selected_values: selected,
    free_text: null,
  })
}

export function setFreeTextAnswer(
  answers: IntentAnswer[],
  questionId: string,
  freeText: string,
): IntentAnswer[] {
  const trimmed = freeText.trim()
  if (!trimmed) {
    return answers.filter((answer) => answer.question_id !== questionId)
  }
  return upsertAnswer(answers, questionId, {
    selected_values: [],
    free_text: trimmed,
  })
}
