import { describe, expect, it, vi } from "vitest"

import { applyPendingAction, type ApplyActionDeps } from "./applyAction"
import type { WordAction } from "./types"

function action(overrides: Partial<WordAction> = {}): WordAction {
  return {
    id: "wa_1",
    job_id: "job_1",
    action_type: "comment",
    content: "Anna: Skärp ingressen.",
    status: "pending",
    anchor: {
      paragraph_index: 1,
      reviewed_text: "Detta stycke är tillräckligt långt.",
      text_hash: "hash",
    },
    ...overrides,
  }
}

function deps(overrides: Partial<ApplyActionDeps> = {}): ApplyActionDeps {
  return {
    readParagraphs: vi.fn(async () => [
      { index: 1, text: "Detta stycke är tillräckligt långt.", style: "Normal", list_string: "" },
    ]),
    paragraphStates: (paragraphs) =>
      paragraphs.map((row) => ({
        paragraph_index: row.index,
        text: row.text,
        unique_local_id: row.unique_local_id ?? null,
      })),
    resolveAnchor: vi.fn(() => ({ status: "resolved" as const, paragraph_index: 1 })),
    wordSessionId: "session",
    newApplicationId: () => "app-1",
    claimAction: vi.fn(async () => ({
      claimed: true,
      action: action({ status: "applying", application_id: "app-1" }),
    })),
    executeWordAction: vi.fn(async () => ({
      status: "resolved" as const,
      wordArtifactId: "word-1",
    })),
    completeAction: vi.fn(async () =>
      action({ status: "applied", application_id: "app-1", word_artifact_id: "word-1" }),
    ),
    markUnresolved: vi.fn(async (_token, _jobId, _actionId, reason) =>
      action({ status: "unresolved", application_error: reason }),
    ),
    reloadAction: vi.fn(async () => null),
    rewritePrefix: "Suggested rewrite:",
    ...overrides,
  }
}

describe("applyPendingAction", () => {
  it("marks missing stale or ambiguous unresolved without claiming or mutating", async () => {
    for (const status of ["stale", "ambiguous", "missing"] as const) {
      const helpers = deps({
        resolveAnchor: vi.fn(() => ({ status })),
      })
      const result = await applyPendingAction("tok", "job_1", action(), helpers)
      expect(result.status).toBe("unresolved")
      expect(result.application_error).toBe(status)
      expect(helpers.claimAction).not.toHaveBeenCalled()
      expect(helpers.executeWordAction).not.toHaveBeenCalled()
      expect(helpers.completeAction).not.toHaveBeenCalled()
    }
  })

  it("claims before the second resolution and mutation", async () => {
    const order: string[] = []
    const helpers = deps({
      claimAction: vi.fn(async () => {
        order.push("claim")
        return { claimed: true, action: action({ status: "applying" }) }
      }),
      executeWordAction: vi.fn(async () => {
        order.push("execute")
        return { status: "resolved" as const, wordArtifactId: "word-1" }
      }),
      completeAction: vi.fn(async () => {
        order.push("complete")
        return action({ status: "applied", word_artifact_id: "word-1" })
      }),
    })
    const result = await applyPendingAction("tok", "job_1", action(), helpers)
    expect(order).toEqual(["claim", "execute", "complete"])
    expect(result.status).toBe("applied")
    expect(helpers.executeWordAction).toHaveBeenCalledTimes(1)
  })

  it("applies replace through executeWordAction", async () => {
    const helpers = deps()
    const replace = action({
      action_type: "replace",
      content: "Ny formulering.",
      explanation: "Tydligare språk.",
    })
    await applyPendingAction("tok", "job_1", replace, helpers)
    expect(helpers.executeWordAction).toHaveBeenCalledWith(replace, {
      rewritePrefix: "Suggested rewrite:",
    })
  })

  it("stays fail-closed applying when mutation throws after claim", async () => {
    const helpers = deps({
      executeWordAction: vi.fn(async () => {
        throw new Error("word crashed")
      }),
    })
    const result = await applyPendingAction("tok", "job_1", action(), helpers)
    expect(result.status).toBe("applying")
    expect(helpers.completeAction).not.toHaveBeenCalled()
  })

  it("does not mutate when claim loses to dismiss", async () => {
    const helpers = deps({
      claimAction: vi.fn(async () => ({ claimed: false })),
      reloadAction: vi.fn(async () => action({ status: "dismissed" })),
    })
    const result = await applyPendingAction("tok", "job_1", action(), helpers)
    expect(result.status).toBe("dismissed")
    expect(helpers.executeWordAction).not.toHaveBeenCalled()
  })
})
