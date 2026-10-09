import { describe, expect, it } from "vitest"
import { acceptModelTraceWorkspace, appendModelTrace, modelTraceEntry } from "./modelTrace"

describe("modelTraceEntry", () => {
  it("keeps a model message and a tool call", () => {
    expect(modelTraceEntry({ kind: "message", text: "Jag jämför villkoren." })).toMatchObject({
      kind: "message",
      text: "Jag jämför villkoren.",
    })
    expect(modelTraceEntry({
      kind: "tool_call",
      name: "read_source",
      call_id: "call_1",
      arguments: { source_id: "avtal" },
    })).toEqual({
      id: "tool_call:call_1",
      kind: "tool_call",
      text: "",
      name: "read_source",
      arguments: { source_id: "avtal" },
    })
  })

  it("drops a message without text and a tool call without a name", () => {
    expect(modelTraceEntry({ kind: "message", text: "  " })).toBeNull()
    expect(modelTraceEntry({ kind: "tool_result", text: "klart" })).toBeNull()
    expect(modelTraceEntry({ kind: "note" })).toBeNull()
  })

  it("keeps traces that omit workspace id and drops a different workspace", () => {
    expect(acceptModelTraceWorkspace("", "workspace-1")).toBe(true)
    expect(acceptModelTraceWorkspace("workspace-1", "workspace-1")).toBe(true)
    expect(acceptModelTraceWorkspace("workspace-2", "workspace-1")).toBe(false)
  })

  it("appends a new trace and skips a duplicate id", () => {
    const first = modelTraceEntry({ kind: "message", text: "Jag läser avtalet." })
    const same = modelTraceEntry({ kind: "message", text: "Jag läser avtalet." })
    const next = modelTraceEntry({ kind: "tool_call", name: "read_source", call_id: "call_1" })
    expect(first).not.toBeNull()
    expect(same).not.toBeNull()
    expect(next).not.toBeNull()
    const rows = appendModelTrace([], first!)
    expect(appendModelTrace(rows, same!)).toEqual(rows)
    expect(appendModelTrace(rows, next!)).toEqual([first, next])
  })
})
