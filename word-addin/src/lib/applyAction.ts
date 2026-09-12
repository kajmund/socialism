import type { WordAction, WordParagraph } from "@/lib/types"
import type { WordAnchorResolution } from "@/lib/word/anchors"
import type { WordActionExecutionOutcome } from "@/lib/word/executeWordAction"

export type ApplyActionDeps = {
  readParagraphs: () => Promise<WordParagraph[]>
  paragraphStates: (
    paragraphs: readonly WordParagraph[],
  ) => { paragraph_index: number; text: string; unique_local_id?: string | null }[]
  resolveAnchor: (
    anchor: NonNullable<WordAction["anchor"]>,
    current: { paragraph_index: number; text: string; unique_local_id?: string | null }[],
    wordSessionId: string,
  ) => WordAnchorResolution
  wordSessionId: string
  newApplicationId: () => string
  claimAction: (
    token: string,
    jobId: string,
    actionId: string,
    applicationId: string,
  ) => Promise<{ claimed: boolean; action?: WordAction }>
  executeWordAction: (
    action: WordAction,
    options: { rewritePrefix: string },
  ) => Promise<WordActionExecutionOutcome>
  completeAction: (
    token: string,
    jobId: string,
    actionId: string,
    applicationId: string,
    wordArtifactId: string,
  ) => Promise<WordAction>
  markUnresolved: (
    token: string,
    jobId: string,
    actionId: string,
    reason: string,
    applicationId?: string,
  ) => Promise<WordAction>
  reloadAction: (jobId: string, actionId: string) => Promise<WordAction | null>
  rewritePrefix: string
}

export async function applyPendingAction(
  token: string,
  jobId: string,
  action: WordAction,
  deps: ApplyActionDeps,
): Promise<WordAction> {
  if (!action.anchor) {
    return deps.markUnresolved(token, jobId, action.id, "missing")
  }

  const current = deps.paragraphStates(await deps.readParagraphs())
  const resolution = deps.resolveAnchor(action.anchor, current, deps.wordSessionId)
  if (resolution.status !== "resolved") {
    return deps.markUnresolved(token, jobId, action.id, resolution.status)
  }

  const applicationId = deps.newApplicationId()
  const claimed = await deps.claimAction(token, jobId, action.id, applicationId)
  if (!claimed.claimed) {
    return (
      claimed.action ??
      (await deps.reloadAction(jobId, action.id)) ??
      action
    )
  }

  try {
    const outcome = await deps.executeWordAction(action, {
      rewritePrefix: deps.rewritePrefix,
    })
    if (outcome.status !== "resolved") {
      return deps.markUnresolved(
        token,
        jobId,
        action.id,
        outcome.status === "unsupported" ? "unsupported_action" : outcome.status,
        applicationId,
      )
    }
    return deps.completeAction(
      token,
      jobId,
      action.id,
      applicationId,
      outcome.wordArtifactId,
    )
  } catch {
    return claimed.action ?? { ...action, status: "applying", application_id: applicationId }
  }
}
