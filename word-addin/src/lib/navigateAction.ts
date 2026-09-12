import type { WordAction, WordParagraph } from "@/lib/types"
import type { WordAnchor, WordAnchorResolution } from "@/lib/word/anchors"

export type NavigateActionDeps = {
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
  revealAnchor: (anchor: WordAnchor) => Promise<WordAnchorResolution>
}

export function locationForAction(
  action: WordAction,
  current: { paragraph_index: number; text: string; unique_local_id?: string | null }[],
  wordSessionId: string,
  resolveAnchor: NavigateActionDeps["resolveAnchor"],
): WordAnchorResolution {
  if (!action.anchor) return { status: "missing" }
  return resolveAnchor(action.anchor, current, wordSessionId)
}

export async function navigateToActionAnchor(
  action: WordAction,
  deps: NavigateActionDeps,
): Promise<WordAnchorResolution> {
  if (!action.anchor) return { status: "missing" }
  const current = deps.paragraphStates(await deps.readParagraphs())
  const resolution = deps.resolveAnchor(action.anchor, current, deps.wordSessionId)
  if (resolution.status !== "resolved") {
    return { status: resolution.status }
  }
  return deps.revealAnchor(action.anchor)
}
