import type { WordAction } from "@/lib/types"

export const ACTION_PENDING = "pending"
export const ACTION_APPLYING = "applying"
export const ACTION_APPLIED = "applied"
export const ACTION_UNRESOLVED = "unresolved"
export const ACTION_DISMISSED = "dismissed"

export function upsertWordActions(
  current: ReadonlyMap<string, WordAction>,
  incoming: readonly WordAction[],
): Map<string, WordAction> {
  const next = new Map(current)
  for (const action of incoming) {
    next.set(action.id, action)
  }
  return next
}

export function sortedWordActions(
  actions: ReadonlyMap<string, WordAction>,
): WordAction[] {
  return [...actions.values()].sort((left, right) => {
    const leftIndex = left.anchor?.paragraph_index ?? Number.MAX_SAFE_INTEGER
    const rightIndex = right.anchor?.paragraph_index ?? Number.MAX_SAFE_INTEGER
    if (leftIndex !== rightIndex) return leftIndex - rightIndex
    const leftOrdinal = left.source?.ordinal ?? Number.MAX_SAFE_INTEGER
    const rightOrdinal = right.source?.ordinal ?? Number.MAX_SAFE_INTEGER
    if (leftOrdinal !== rightOrdinal) return leftOrdinal - rightOrdinal
    return left.id.localeCompare(right.id)
  })
}

export function canApplyAction(status: string): boolean {
  return status === ACTION_PENDING
}

export function canDismissAction(status: string): boolean {
  return status === ACTION_PENDING || status === ACTION_UNRESOLVED
}

export type NewReviewBlock = "undecided" | "applying"

export function newReviewBlock(
  actions: readonly WordAction[],
): NewReviewBlock | null {
  if (actions.some((row) => row.status === ACTION_APPLYING)) {
    return "applying"
  }
  if (
    actions.some(
      (row) => row.status === ACTION_PENDING || row.status === ACTION_UNRESOLVED,
    )
  ) {
    return "undecided"
  }
  return null
}

export type ActionCardKind = "comment" | "replace" | "unknown"

export function actionCardKind(actionType: string): ActionCardKind {
  switch (actionType) {
    case "comment":
      return "comment"
    case "replace":
      return "replace"
    default:
      return "unknown"
  }
}

export type UnresolvedReason =
  | "stale"
  | "ambiguous"
  | "missing"
  | "unsupported_action"
  | "unknown"

export function unresolvedReasonKind(code: string | null | undefined): UnresolvedReason {
  switch (code) {
    case "stale":
    case "ambiguous":
    case "missing":
    case "unsupported_action":
      return code
    default:
      return "unknown"
  }
}

export type ActionCardModel = {
  id: string
  kind: ActionCardKind
  content: string
  reviewedText: string | null
  explanation: string | null
  status: string
  unresolvedReason: UnresolvedReason | null
  showApply: boolean
  showDismiss: boolean
  showApplying: boolean
  deemphasized: boolean
}

export function actionCardModel(action: WordAction): ActionCardModel {
  const kind = actionCardKind(action.action_type)
  const unresolvedReason =
    action.status === ACTION_UNRESOLVED
      ? unresolvedReasonKind((action.application_error ?? "").trim() || null)
      : null
  return {
    id: action.id,
    kind,
    content: action.content,
    reviewedText: kind === "replace" ? (action.anchor?.reviewed_text ?? "") : null,
    explanation: kind === "replace" ? (action.explanation ?? "").trim() || null : null,
    status: action.status,
    unresolvedReason,
    showApply: canApplyAction(action.status),
    showDismiss: canDismissAction(action.status),
    showApplying: action.status === ACTION_APPLYING,
    deemphasized:
      action.status === ACTION_APPLIED || action.status === ACTION_DISMISSED,
  }
}

export function wordArtifactIds(actions: readonly WordAction[]): string[] {
  return actions
    .map((row) => row.word_artifact_id)
    .filter((id): id is string => typeof id === "string" && id.length > 0)
}
