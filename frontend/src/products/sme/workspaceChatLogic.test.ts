import { ApiError } from "@/lib/http"
import { describe, expect, it } from "vitest"
import type { WorkspaceMessage, WorkspaceState } from "@/api/voiceWorkspaces"
import { clientArguments, isCurrentConversation, openWorkspaceDocument, upsertTranscript, workspaceThreadKey, workspaceErrorMessage } from "./workspaceChatLogic"
const state: WorkspaceState = { language: "sv", knowledge_scope: "workspace", view: "relations", documents: [{ source_id: "first", page: 3, zoom: 1.5 }, { source_id: "second", page: 7, zoom: 0.8 }], split_source_ids: ["first", "second"], research_attempt_ids: [], selection: { node_id: "event" } }
const message: WorkspaceMessage = { id: 10, role: "agent", content: "The complete response", session_id: "session-a", event_key: "agent:4", created_at: "2026-10-04T12:00:00Z" }
describe("workspace conversation state", () => {
  it("accepts callbacks only for the current generation and chat scope", () => {
    const scope = { workspaceId: "canvas-a", expertId: "expert-a" }
    expect(isCurrentConversation(2, 2, scope, scope)).toBe(true)
    expect(isCurrentConversation(2, 3, scope, scope)).toBe(false)
  })
  it("rejects an old workspace or expert before effect cleanup advances the generation", () => {
    const scope = { workspaceId: "canvas-a", expertId: "expert-a" }
    expect(isCurrentConversation(2, 2, scope, { ...scope, workspaceId: "canvas-b" })).toBe(false)
    expect(isCurrentConversation(2, 2, scope, { ...scope, expertId: "expert-b" })).toBe(false)
    expect(isCurrentConversation(2, 2, scope, { workspaceId: null, expertId: null })).toBe(false)
  })
  it("explains provider errors and stale sources without exposing machine codes", () => {
    const translate = (key: string) => key
    expect(workspaceErrorMessage(new ApiError("elevenlabs_voice_unavailable", { status: 503 }), translate, "voiceWorkspaceChat.sessionError")).toBe("voiceWorkspaceChat.sessionError")
    expect(workspaceErrorMessage(new ApiError("workspace_reference_stale", { status: 409 }), translate)).toBe("voiceWorkspaceChat.stale")
    expect(workspaceErrorMessage(new ApiError("workspace_revision_conflict", { status: 409 }), translate)).toBe("voiceWorkspaceChat.conflict")
  })
  it("isolates drafts for the same expert in different workspaces", () => {
    expect(workspaceThreadKey("workspace-a", "expert", "same-expert")).not.toBe(workspaceThreadKey("workspace-b", "expert", "same-expert"))
    expect(workspaceThreadKey("workspace-a", "expert", "same-expert")).not.toBe(workspaceThreadKey("workspace-a", "panel", "same-expert"))
  })
  it("corrects the same transcript without duplicating a replayed event", () => {
    const corrected = { ...message, content: "The spoken response" }
    const rows = upsertTranscript(upsertTranscript([message], corrected), corrected)
    expect(rows).toEqual([corrected])
  })
  it("keeps equal native event IDs separate across provider sessions", () => {
    expect(upsertTranscript([message], { ...message, id: 11, session_id: "session-b" })).toHaveLength(2)
  })
  it("opens the cited page and preserves each document's own zoom", () => {
    const next = openWorkspaceDocument(state, "second", 9)
    expect(next.documents).toEqual([{ source_id: "second", page: 9, zoom: 0.8 }, state.documents[0]])
    expect(state.documents[1].page).toBe(7)
  })
  it("rejects malformed native tool JSON before executing a UI operation", () => {
    expect(clientArguments({ arguments_json: '{"reference_id":"ref-a"}' })).toEqual({ reference_id: "ref-a" })
    expect(() => clientArguments({ arguments_json: "[]" })).toThrow()
    expect(() => clientArguments({ arguments_json: "{" })).toThrow()
  })
})
