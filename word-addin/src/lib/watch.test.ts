import { describe, expect, it } from "vitest"

import type { WatchEvent, WordAction } from "./types"
import { actionsForWatchEvent, shouldAutoApplyAction } from "./watch"

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

describe("shouldAutoApplyAction", () => {
  it("inserts a new pending action once", () => {
    const inserted = new Set<string>()
    expect(shouldAutoApplyAction(inserted, action())).toBe(true)
    inserted.add("wa_1")
    expect(shouldAutoApplyAction(inserted, action())).toBe(false)
  })

  it("skips actions that already have a Word artifact", () => {
    expect(
      shouldAutoApplyAction(
        new Set(),
        action({ word_artifact_id: "c1", status: "applied" }),
      ),
    ).toBe(false)
  })

  it("never auto-applies applying, applied, or unresolved actions", () => {
    expect(shouldAutoApplyAction(new Set(), action({ status: "applying" }))).toBe(false)
    expect(shouldAutoApplyAction(new Set(), action({ status: "applied" }))).toBe(false)
    expect(shouldAutoApplyAction(new Set(), action({ status: "unresolved" }))).toBe(false)
  })

  it("inserts replace actions when content is present", () => {
    expect(
      shouldAutoApplyAction(
        new Set(),
        action({
          action_type: "replace",
          content: "Ny formulering.",
          explanation: null,
        }),
      ),
    ).toBe(true)
  })

  it("skips actions without content", () => {
    expect(shouldAutoApplyAction(new Set(), action({ content: "  " }))).toBe(false)
  })
})

describe("actionsForWatchEvent", () => {
  it("dedupes an action that arrives in both replay and created", () => {
    const inserted = new Set<string>()
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

    const fromReplay = actionsForWatchEvent(replay, inserted)
    expect(fromReplay).toEqual([{ kind: "insert", actions: [row] }])
    inserted.add("wa_race")

    expect(actionsForWatchEvent(created, inserted)).toEqual([
      { kind: "remember", ids: ["wa_race"] },
    ])
  })

  it("does not insert again when complete echoes action.updated", () => {
    const inserted = new Set(["wa_1"])
    const updated: WatchEvent = {
      type: "expertgranskning.action.updated",
      job_id: "job_1",
      action: action({ word_artifact_id: "word-1", status: "applied" }),
    }
    expect(actionsForWatchEvent(updated, inserted)).toEqual([
      { kind: "remember", ids: ["wa_1"] },
    ])
  })

  it("replays already-applied actions into the dedupe set without inserting", () => {
    const posted = action({ id: "wa_old", word_artifact_id: "word-9", status: "applied" })
    const replay: WatchEvent = {
      type: "expertgranskning.replay",
      job_id: "job_1",
      status: "running",
      actions: [posted],
    }
    expect(actionsForWatchEvent(replay, new Set())).toEqual([
      { kind: "remember", ids: ["wa_old"] },
    ])
  })

  it("remembers applying and unresolved actions without inserting", () => {
    const applying = action({ id: "wa_applying", status: "applying" })
    const unresolved = action({ id: "wa_unresolved", status: "unresolved" })
    const replay: WatchEvent = {
      type: "expertgranskning.replay",
      job_id: "job_1",
      status: "running",
      actions: [applying, unresolved],
    }
    expect(actionsForWatchEvent(replay, new Set())).toEqual([
      { kind: "remember", ids: ["wa_applying", "wa_unresolved"] },
    ])
  })

  it("surfaces finished status", () => {
    expect(
      actionsForWatchEvent(
        { type: "expertgranskning.finished", job_id: "job_1", status: "succeeded" },
        new Set(),
      ),
    ).toEqual([{ kind: "finished", status: "succeeded" }])
  })
})
