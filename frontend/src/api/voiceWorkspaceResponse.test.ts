import { describe, expect, it } from "vitest"
import { requireVoiceWorkspace } from "./voiceWorkspaceResponse"

describe("voice workspace response", () => {
  const workspace = {
    id: "canvas", workspace_id: "company", chat_id: "private-chat", customer_id: 1, revision: 0,
    title: "Chat", module: "dd", sources: [], artifacts: [], references: [], research: [],
    state: { language: "sv", knowledge_scope: "workspace", view: "evidence", documents: [], split_source_ids: [], research_attempt_ids: [] },
  }

  it("accepts the complete canvas returned by create, read and patch", () => {
    expect(requireVoiceWorkspace(workspace)).toBe(workspace)
  })

  it("rejects an empty operation result before it replaces the visible workspace", () => {
    expect(() => requireVoiceWorkspace({})).toThrow("voice_workspace_response_invalid")
    expect(() => requireVoiceWorkspace({ ...workspace, state: undefined })).toThrow("voice_workspace_response_invalid")
  })
})
