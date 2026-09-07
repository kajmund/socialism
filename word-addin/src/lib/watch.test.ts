import { describe, expect, it } from "vitest"

import type { ReviewResult, WatchEvent } from "./types"
import { actionsForWatchEvent, formatCommentBody, shouldInsertComment } from "./watch"

function result(overrides: Partial<ReviewResult> = {}): ReviewResult {
  return {
    id: "egr_1",
    job_id: "job_1",
    paragraph_index: 1,
    expert_id: "slot_1",
    expert_namn: "Anna",
    kommentar: "Skärp ingressen.",
    is_heading_suggestion: false,
    comment_id: null,
    status: "pending",
    ...overrides,
  }
}

describe("shouldInsertComment", () => {
  it("inserts a new pending row once", () => {
    const inserted = new Set<string>()
    expect(shouldInsertComment(inserted, result())).toBe(true)
    inserted.add("egr_1")
    expect(shouldInsertComment(inserted, result())).toBe(false)
  })

  it("skips rows that already have a Word comment_id", () => {
    expect(
      shouldInsertComment(new Set(), result({ comment_id: "c1", status: "posted" })),
    ).toBe(false)
  })
})

describe("actionsForWatchEvent", () => {
  it("dedupes a row that arrives in both replay and created", () => {
    const inserted = new Set<string>()
    const row = result({ id: "egr_race" })
    const replay: WatchEvent = {
      type: "expertgranskning.replay",
      job_id: "job_1",
      status: "running",
      results: [row],
    }
    const created: WatchEvent = {
      type: "expertgranskning.result.created",
      job_id: "job_1",
      result: row,
    }

    const fromReplay = actionsForWatchEvent(replay, inserted)
    expect(fromReplay).toEqual([{ kind: "insert", results: [row] }])
    inserted.add("egr_race")

    expect(actionsForWatchEvent(created, inserted)).toEqual([
      { kind: "remember", ids: ["egr_race"] },
    ])
  })

  it("does not insert again when PATCH echoes result.updated", () => {
    const inserted = new Set(["egr_1"])
    const updated: WatchEvent = {
      type: "expertgranskning.result.updated",
      job_id: "job_1",
      result: result({ comment_id: "word-1", status: "posted" }),
    }
    expect(actionsForWatchEvent(updated, inserted)).toEqual([
      { kind: "remember", ids: ["egr_1"] },
    ])
  })

  it("replays already-posted rows into the dedupe set without inserting", () => {
    const posted = result({ id: "egr_old", comment_id: "word-9", status: "posted" })
    const replay: WatchEvent = {
      type: "expertgranskning.replay",
      job_id: "job_1",
      status: "running",
      results: [posted],
    }
    expect(actionsForWatchEvent(replay, new Set())).toEqual([
      { kind: "remember", ids: ["egr_old"] },
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

describe("formatCommentBody", () => {
  it("prefixes body comments with the expert name", () => {
    expect(formatCommentBody(result())).toBe("Anna: Skärp ingressen.")
  })

  it("leaves heading suggestions unprefixed", () => {
    expect(
      formatCommentBody(
        result({ is_heading_suggestion: true, expert_namn: "", kommentar: "Ny rubrik" }),
      ),
    ).toBe("Ny rubrik")
  })
})
