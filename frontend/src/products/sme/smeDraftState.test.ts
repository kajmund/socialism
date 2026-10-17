import { describe, expect, it } from "vitest"
import {
  INITIAL_DRAFT_STATE,
  reduceDraftPreview,
  type DraftStreamState,
} from "./smeDraftState"

function reduce(
  state: DraftStreamState,
  events: Parameters<typeof reduceDraftPreview>[1][],
): DraftStreamState {
  return events.reduce(reduceDraftPreview, state)
}

describe("reduceDraftPreview", () => {
  it("accumulates draft tokens into the acknowledgment", () => {
    const state = reduce(INITIAL_DRAFT_STATE, [
      { type: "draft_token", text: "Ok, " },
      { type: "draft_token", text: "jag kollar." },
    ])
    expect(state).toEqual({ final: false, draft: "Ok, jag kollar." })
  })

  it("closes the buffer on a terminal event and ignores later tokens", () => {
    const state = reduce(INITIAL_DRAFT_STATE, [
      { type: "draft_token", text: "Ok, " },
      { type: "close" },
      { type: "draft_token", text: " sent" },
    ])
    expect(state).toEqual({ final: true, draft: null })
  })
})
