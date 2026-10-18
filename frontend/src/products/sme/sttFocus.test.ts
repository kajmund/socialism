import { describe, expect, it } from "vitest"
import { sourceIdsFromWorkspaceContext } from "./sttFocus"

describe("sourceIdsFromWorkspaceContext", () => {
  it("uses the open document from a workspace state update", () => {
    const text = `Workspace state updated: ${JSON.stringify({
      documents: [{ source_id: "avtal" }, { source_id: "annex" }],
      split_source_ids: [],
    })}`
    expect(sourceIdsFromWorkspaceContext(text)).toEqual(["avtal"])
  })

  it("prefers the active source when tab order differs", () => {
    const text = `Workspace state updated: ${JSON.stringify({
      documents: [{ source_id: "avtal" }, { source_id: "annex" }],
      active_source_id: "annex",
      split_source_ids: [],
    })}`
    expect(sourceIdsFromWorkspaceContext(text)).toEqual(["annex"])
  })

  it("uses both panes when the workspace is split", () => {
    const text = `Workspace state updated: ${JSON.stringify({
      documents: [{ source_id: "avtal" }],
      split_source_ids: ["left", "right"],
    })}`
    expect(sourceIdsFromWorkspaceContext(text)).toEqual(["left", "right"])
  })

  it("ignores other context lines", () => {
    expect(sourceIdsFromWorkspaceContext("Workspace background jobs updated: []")).toBeNull()
  })
})
