import { describe, expect, it } from "vitest"

import { createWordTask } from "./task"
import {
  mapSelectionByEqualRanges,
  mapSelectionByUniqueLocalId,
} from "./taskSnapshot"

describe("mapSelectionByUniqueLocalId", () => {
  it("maps selected local ids to global paragraph indexes", () => {
    expect(
      mapSelectionByUniqueLocalId(
        ["p-0", "p-1", "p-2", "p-3"],
        ["p-2", "p-1"],
      ),
    ).toEqual([1, 2])
  })

  it("keeps a single selected paragraph", () => {
    expect(mapSelectionByUniqueLocalId(["a", "b", "c"], ["b"])).toEqual([1])
  })

  it("does not map by text and fails closed on duplicate ids", () => {
    expect(
      mapSelectionByUniqueLocalId(["dup", "dup", "c"], ["dup"]),
    ).toBeNull()
  })

  it("fails closed when any id is missing", () => {
    expect(mapSelectionByUniqueLocalId(["a", "b"], ["a", null])).toBeNull()
    expect(mapSelectionByUniqueLocalId(["a", null], ["a"])).toBeNull()
  })
})

describe("mapSelectionByEqualRanges", () => {
  it("expands a partial multi-paragraph selection to containing indexes", () => {
    expect(mapSelectionByEqualRanges([[14], [15], [16]])).toEqual([14, 15, 16])
  })

  it("fails closed when a selected paragraph has no unique equal match", () => {
    expect(mapSelectionByEqualRanges([[14], [], [16]])).toBeNull()
    expect(mapSelectionByEqualRanges([[14, 99]])).toBeNull()
  })
})

describe("createWordTask", () => {
  it("builds a review task with panel strategy", () => {
    expect(
      createWordTask({
        panelId: 12,
        scope: { type: "selection", paragraph_indexes: [14, 15] },
      }),
    ).toEqual({
      task_type: "review",
      scope: { type: "selection", paragraph_indexes: [14, 15] },
      expert_strategy: { type: "panel", panel_id: 12 },
    })
  })
})
