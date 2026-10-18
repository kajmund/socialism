/**
 * Client-side protocol for the SME quick acknowledgment stream.
 *
 * The backend streams `draft_token` events from the fast model while the full
 * reply is generated. The acknowledgment stays visible as its own bubble and
 * the full reply streams below it; once the turn is terminal the buffer is
 * closed and later draft tokens are ignored, so an interrupted stream never
 * revives a half-written message.
 */
export type DraftStreamEvent =
  | { type: "draft_token"; text: string }
  | { type: "close" }

export type DraftStreamState = {
  final: boolean
  draft: string | null
}

export const INITIAL_DRAFT_STATE: DraftStreamState = {
  final: false,
  draft: null,
}

export function reduceDraftPreview(
  state: DraftStreamState,
  event: DraftStreamEvent,
): DraftStreamState {
  switch (event.type) {
    case "draft_token":
      if (state.final) return state
      return { final: false, draft: (state.draft ?? "") + event.text }
    case "close":
      return { final: true, draft: null }
  }
}
