import { describe, expect, it } from "vitest"

import type { WatchEvent, WordAction } from "./types"
import { actionsForWatchEvent } from "./watch"

function action(overrides: Partial<WordAction> = {}): WordAction {
  return {
    id: "wa_1",
    job_id: "job_1",
    action_type: "comment",
    content: "Anna: Skärp ingressen.",
    explanation: null,
    word_artifact_id: null,
    status: "pending",
    ...overrides,
  }
}

describe("actionsForWatchEvent", () => {
  it("upserts replay and created without scheduling apply", () => {
    const row = action({ id: "wa_race" })
    const replay: WatchEvent = {
      type: "expertgranskning.replay",
      job_id: "job_1",
      status: "running",
      actions: [row],
    }
    const created: WatchEvent = {
      type: "expertgranskning.action.created",
      job_id: "job_1",
      action: row,
    }
    expect(actionsForWatchEvent(replay)).toEqual([{ kind: "upsert", actions: [row] }])
    expect(actionsForWatchEvent(created)).toEqual([{ kind: "upsert", actions: [row] }])
  })

  it("replaces the current version on updated", () => {
    const updated = action({ status: "dismissed" })
    expect(
      actionsForWatchEvent({
        type: "expertgranskning.action.updated",
        job_id: "job_1",
        action: updated,
      }),
    ).toEqual([{ kind: "upsert", actions: [updated] }])
  })

  it("upserts applying applied and dismissed without auto-retry", () => {
    const rows = [
      action({ id: "wa_applying", status: "applying" }),
      action({ id: "wa_applied", status: "applied", word_artifact_id: "word-1" }),
      action({ id: "wa_dismissed", status: "dismissed" }),
    ]
    expect(
      actionsForWatchEvent({
        type: "expertgranskning.replay",
        job_id: "job_1",
        status: "succeeded",
        actions: rows,
      }),
    ).toEqual([{ kind: "upsert", actions: rows }])
  })

  it("surfaces finished without clearing actions", () => {
    expect(
      actionsForWatchEvent({
        type: "expertgranskning.finished",
        job_id: "job_1",
        status: "succeeded",
      }),
    ).toEqual([{ kind: "finished", status: "succeeded" }])
  })
})
