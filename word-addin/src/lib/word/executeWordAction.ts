import {
  insertCommentForAnchor,
  replaceForAnchor,
  type WordMutationOutcome,
} from "@/lib/office"
import type { WordAction } from "@/lib/types"

export type WordActionKind = "comment" | "replace" | "unsupported"

export type WordActionExecutionOutcome =
  | { status: "resolved"; wordArtifactId: string }
  | { status: "stale" | "ambiguous" | "missing" | "unsupported" }

export function wordActionKind(actionType: string): WordActionKind {
  switch (actionType) {
    case "comment":
      return "comment"
    case "replace":
      return "replace"
    default:
      return "unsupported"
  }
}

function mapMutation(
  outcome: WordMutationOutcome,
): WordActionExecutionOutcome {
  if (outcome.status === "resolved") {
    return { status: "resolved", wordArtifactId: outcome.commentId }
  }
  return { status: outcome.status }
}

export async function executeWordAction(
  action: WordAction,
  options: { rewritePrefix: string },
): Promise<WordActionExecutionOutcome> {
  const kind = wordActionKind(action.action_type)
  if (kind === "unsupported") {
    return { status: "unsupported" }
  }
  if (!action.anchor) {
    return { status: "missing" }
  }
  switch (kind) {
    case "comment":
      return mapMutation(await insertCommentForAnchor(action.anchor, action.content))
    case "replace":
      return mapMutation(
        await replaceForAnchor({
          anchor: action.anchor,
          replacementText: action.content,
          explanation: (action.explanation ?? "").trim() || options.rewritePrefix,
          fallbackComment: `${options.rewritePrefix} ${action.content}`.trim(),
        }),
      )
    default: {
      const _exhaustive: never = kind
      return _exhaustive
    }
  }
}
