import { answersReady } from "@/lib/intentInterview"
import type {
  DocumentIntentInterview,
  IntentAnswer,
  LatestWordJob,
  WordReviewContext,
} from "@/lib/types"

export function localeForReview(locale: string): "sv" | "en" {
  return locale === "en" ? "en" : "sv"
}

export function savedReviewContext(
  latest: LatestWordJob | null,
): WordReviewContext | null {
  const context = latest?.review_context
  if (context == null || context.intent_interview == null) return null
  if (!answersReady(context.intent_interview, context.intent_answers)) return null
  return context
}

export function shouldGenerateIntentInterview(args: {
  context: WordReviewContext | null
  locale: "sv" | "en"
  resetRequested: boolean
}): boolean {
  if (args.resetRequested) return true
  if (args.context == null) return true
  return localeForReview(args.context.locale) !== args.locale
}

export function interviewDraftLocaleMismatch(args: {
  draftLocale: "sv" | "en" | undefined
  locale: "sv" | "en"
}): boolean {
  if (args.draftLocale == null) return true
  return args.draftLocale !== args.locale
}

export function reusedIntentPayload(context: WordReviewContext): {
  interview: DocumentIntentInterview
  answers: IntentAnswer[]
  reviewIntent: string
} {
  if (context.intent_interview == null) {
    throw new Error("review_context_missing_interview")
  }
  return {
    interview: context.intent_interview,
    answers: context.intent_answers,
    reviewIntent: context.review_intent,
  }
}
