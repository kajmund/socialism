import { describe, expect, it, vi } from "vitest"

import { locationForAction, navigateToActionAnchor, type NavigateActionDeps } from "./navigateAction"
import type { WordAction } from "./types"
import { hashWordText, resolveWordAnchor } from "./word/anchors"

function action(overrides: Partial<WordAction> = {}): WordAction {
  return {
    id: "wa_1",
    job_id: "job_1",
    action_type: "comment",
    content: "Anna: Skärp ingressen.",
    status: "pending",
    anchor: {
      paragraph_index: 99,
      reviewed_text: "Detta stycke är tillräckligt långt.",
      text_hash: hashWordText("Detta stycke är tillräckligt långt."),
    },
    ...overrides,
  }
}

function deps(overrides: Partial<NavigateActionDeps> = {}): NavigateActionDeps {
  return {
    readParagraphs: vi.fn(async () => [
      { index: 0, text: "Ingress.", style: "Normal", list_string: "" },
      {
        index: 2,
        text: "Detta stycke är tillräckligt långt.",
        style: "Normal",
        list_string: "",
      },
    ]),
    paragraphStates: (paragraphs) =>
      paragraphs.map((row) => ({
        paragraph_index: row.index,
        text: row.text,
        unique_local_id: row.unique_local_id ?? null,
      })),
    resolveAnchor: resolveWordAnchor,
    wordSessionId: "session",
    revealAnchor: vi.fn(async () => ({ status: "resolved" as const, paragraph_index: 2 })),
    ...overrides,
  }
}

describe("locationForAction", () => {
  it("uses the Apply resolver, not the raw paragraph_index", () => {
    const row = action()
    const current = [
      { paragraph_index: 0, text: "Ingress." },
      { paragraph_index: 2, text: "Detta stycke är tillräckligt långt." },
    ]
    expect(locationForAction(row, current, "session", resolveWordAnchor)).toEqual({
      status: "resolved",
      paragraph_index: 2,
    })
    expect(row.anchor?.paragraph_index).toBe(99)
  })

  it("returns missing when the action has no anchor", () => {
    expect(
      locationForAction(action({ anchor: null }), [], "session", resolveWordAnchor),
    ).toEqual({ status: "missing" })
  })
})

describe("navigateToActionAnchor", () => {
  it("reveals the resolved target and does not pass the raw index", async () => {
    const helpers = deps()
    const row = action()
    const result = await navigateToActionAnchor(row, helpers)
    expect(result).toEqual({ status: "resolved", paragraph_index: 2 })
    expect(helpers.revealAnchor).toHaveBeenCalledTimes(1)
    expect(helpers.revealAnchor).toHaveBeenCalledWith(row.anchor)
  })

  it("does not jump when the resolver reports stale missing or ambiguous", async () => {
    for (const status of ["stale", "ambiguous", "missing"] as const) {
      const helpers = deps({
        resolveAnchor: vi.fn(() => ({ status })),
      })
      const result = await navigateToActionAnchor(action(), helpers)
      expect(result).toEqual({ status })
      expect(helpers.revealAnchor).not.toHaveBeenCalled()
    }
  })

  it("does not guess a location when the action has no anchor", async () => {
    const helpers = deps()
    const result = await navigateToActionAnchor(action({ anchor: null }), helpers)
    expect(result).toEqual({ status: "missing" })
    expect(helpers.readParagraphs).not.toHaveBeenCalled()
    expect(helpers.revealAnchor).not.toHaveBeenCalled()
  })
})
