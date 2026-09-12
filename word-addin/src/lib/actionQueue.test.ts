import { describe, expect, it } from "vitest"

import {
  actionCardModel,
  canApplyAction,
  canDismissAction,
  newReviewBlock,
  sortedWordActions,
  unresolvedReasonKind,
  upsertWordActions,
  wordArtifactIds,
} from "./actionQueue"
import type { WordAction } from "./types"

function action(overrides: Partial<WordAction> = {}): WordAction {
  return {
    id: "wa_1",
    job_id: "job_1",
    action_type: "comment",
    content: "Anna: Skärp ingressen.",
    explanation: null,
    status: "pending",
    created_at: "2026-09-12T10:00:00+00:00",
    ...overrides,
  }
}

describe("upsertWordActions", () => {
  it("inserts and replaces by id so replay plus created is one card", () => {
    const first = action({ id: "wa_a", status: "pending" })
    const replay = upsertWordActions(new Map(), [first, action({ id: "wa_b" })])
    const created = upsertWordActions(replay, [
      action({ id: "wa_a", status: "pending", content: "Anna: Skärp ingressen." }),
    ])
    const updated = upsertWordActions(created, [
      action({ id: "wa_a", status: "applied" }),
    ])
    expect([...updated.keys()].sort()).toEqual(["wa_a", "wa_b"])
    expect(updated.get("wa_a")?.status).toBe("applied")
  })
})

describe("sortedWordActions", () => {
  it("orders by paragraph_index then stable id", () => {
    const map = upsertWordActions(new Map(), [
      action({
        id: "wa_c",
        created_at: "2026-09-12T10:00:00+00:00",
        anchor: { paragraph_index: 8, reviewed_text: "c", text_hash: "c" },
      }),
      action({
        id: "wa_b",
        created_at: "2026-09-12T12:00:00+00:00",
        anchor: { paragraph_index: 2, reviewed_text: "b", text_hash: "b" },
      }),
      action({
        id: "wa_a",
        created_at: "2026-09-12T11:00:00+00:00",
        anchor: { paragraph_index: 2, reviewed_text: "a", text_hash: "a" },
      }),
    ])
    expect(sortedWordActions(map).map((row) => row.id)).toEqual([
      "wa_a",
      "wa_b",
      "wa_c",
    ])
  })
})

describe("actionCardModel", () => {
  it("renders comment content with apply and dismiss while pending", () => {
    const model = actionCardModel(action())
    expect(model.kind).toBe("comment")
    expect(model.content).toBe("Anna: Skärp ingressen.")
    expect(model.reviewedText).toBeNull()
    expect(model.showApply).toBe(true)
    expect(model.showDismiss).toBe(true)
    expect(model.showApplying).toBe(false)
  })

  it("renders replace current, suggested, and explanation", () => {
    const model = actionCardModel(
      action({
        action_type: "replace",
        content: "Ny formulering.",
        explanation: "Tydligare språk.",
        anchor: {
          paragraph_index: 1,
          reviewed_text: "Gammal text.",
          text_hash: "hash",
        },
      }),
    )
    expect(model.kind).toBe("replace")
    expect(model.reviewedText).toBe("Gammal text.")
    expect(model.content).toBe("Ny formulering.")
    expect(model.explanation).toBe("Tydligare språk.")
    expect(JSON.stringify(model)).not.toContain("expert_id")
    expect(JSON.stringify(model)).not.toContain("foreslagen_text")
    expect(JSON.stringify(model)).not.toContain("is_rewrite_suggestion")
  })

  it("shows applying without executable controls", () => {
    const model = actionCardModel(action({ status: "applying" }))
    expect(model.showApply).toBe(false)
    expect(model.showDismiss).toBe(false)
    expect(model.showApplying).toBe(true)
    expect(model.deemphasized).toBe(false)
  })

  it("deemphasizes applied and dismissed and hides apply", () => {
    expect(actionCardModel(action({ status: "applied" }))).toMatchObject({
      showApply: false,
      showDismiss: false,
      deemphasized: true,
    })
    expect(actionCardModel(action({ status: "dismissed" }))).toMatchObject({
      showApply: false,
      showDismiss: false,
      deemphasized: true,
    })
  })

  it("maps unresolved backend codes without exposing them as UI copy", () => {
    expect(
      actionCardModel(action({ status: "unresolved", application_error: "stale" })),
    ).toMatchObject({
      unresolvedReason: "stale",
      showApply: false,
      showDismiss: true,
    })
    expect(
      actionCardModel(
        action({ status: "unresolved", application_error: "unsupported_action" }),
      ).unresolvedReason,
    ).toBe("unsupported_action")
    expect(
      actionCardModel(action({ status: "unresolved", application_error: "weird" }))
        .unresolvedReason,
    ).toBe("unknown")
    expect(unresolvedReasonKind("stale")).toBe("stale")
    expect(unresolvedReasonKind("ambiguous")).toBe("ambiguous")
    expect(unresolvedReasonKind("missing")).toBe("missing")
    expect(unresolvedReasonKind("unsupported_action")).toBe("unsupported_action")
    expect(unresolvedReasonKind("")).toBe("unknown")
  })
})

describe("apply and dismiss gates", () => {
  it("only pending can apply", () => {
    expect(canApplyAction("pending")).toBe(true)
    expect(canApplyAction("applying")).toBe(false)
    expect(canApplyAction("applied")).toBe(false)
    expect(canApplyAction("dismissed")).toBe(false)
    expect(canApplyAction("unresolved")).toBe(false)
  })

  it("only pending and unresolved can dismiss", () => {
    expect(canDismissAction("pending")).toBe(true)
    expect(canDismissAction("unresolved")).toBe(true)
    expect(canDismissAction("applying")).toBe(false)
    expect(canDismissAction("applied")).toBe(false)
    expect(canDismissAction("dismissed")).toBe(false)
  })
})

describe("newReviewBlock", () => {
  it("blocks applying first, then undecided, and allows settled actions", () => {
    expect(newReviewBlock([action({ status: "applying" })])).toBe("applying")
    expect(newReviewBlock([action({ status: "pending" })])).toBe("undecided")
    expect(newReviewBlock([action({ status: "unresolved" })])).toBe("undecided")
    expect(
      newReviewBlock([
        action({ status: "applied", word_artifact_id: "word-1" }),
        action({ id: "wa_2", status: "dismissed" }),
      ]),
    ).toBeNull()
  })

  it("passes only real word artifacts to cleanup", () => {
    expect(
      wordArtifactIds([
        action({ status: "applied", word_artifact_id: "word-1" }),
        action({ id: "wa_2", status: "dismissed", word_artifact_id: null }),
        action({ id: "wa_3", status: "pending", word_artifact_id: "" }),
      ]),
    ).toEqual(["word-1"])
  })
})
