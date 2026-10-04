import { describe, expect, it } from "vitest"
import type { WorkspaceFile } from "@/api/workspaces"
import { safeSourceUrl, selectedFilesBlocked, workspaceFileState } from "./workspaceChatState"

const file = (id: string, knowledge_status: WorkspaceFile["knowledge_status"]): WorkspaceFile => ({
  id, knowledge_status, workspace_id: "client", extraction_status: "ok", kind: "underlag",
  filename: "avtal.md", content_type: "text/markdown", size_bytes: 40, module: "dd",
  owner_user_id: null, folder_id: null, created_at: "2026-10-04",
})

describe("workspace research document readiness", () => {
  it("blocks selected pending documents rather than silently dropping them", () => {
    expect(selectedFilesBlocked([file("a", "ready"), file("b", "pending")], ["a", "b"])).toBe(true)
    expect(selectedFilesBlocked([file("a", "ready"), file("b", "pending")], ["a"])).toBe(false)
  })
  it("blocks a selected document removed from the accessible list", () => {
    expect(selectedFilesBlocked([file("a", "ready")], ["foreign"])).toBe(true)
  })
  it("distinguishes upload, ingest, usable content and failures", () => {
    expect(workspaceFileState(file("a", "pending"))).toBe("uploaded")
    expect(workspaceFileState(file("a", "running"))).toBe("ingesting")
    expect(workspaceFileState(file("a", "ready"))).toBe("ready")
    expect(workspaceFileState(file("a", "partial"))).toBe("failed")
    expect(workspaceFileState(file("a", "failed"))).toBe("failed")
  })
  it("accepts research with an explicit empty document selection", () => {
    expect(selectedFilesBlocked([file("a", "pending")], [])).toBe(false)
  })
})

describe("research citation links", () => {
  it("permits web sources and rejects script and local URLs", () => {
    expect(safeSourceUrl("https://lagen.nu/2020:1")).toBe("https://lagen.nu/2020:1")
    expect(safeSourceUrl("javascript:alert(1)")).toBe(null)
    expect(safeSourceUrl("file:///etc/passwd")).toBe(null)
    expect(safeSourceUrl("/private/document")).toBe(null)
  })
})
