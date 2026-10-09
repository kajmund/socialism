import { ApiError } from "@/lib/http"
import { describe, expect, it } from "vitest"
import type { WorkspaceMessage, WorkspaceState } from "@/api/voiceWorkspaces"
import { artifactPresentationKey, clientArguments, clientToolFailure, commitWorkspaceState, expertProxyToolNames, interviewTranscriptMessage, isCurrentConversation, isWorkspaceSourceReread, mergeTranscript, openWorkspaceDocument, sameArtifactContent, sameWorkspaceState, takeReadyGenerationArtifact, upsertTranscript, workspaceGenerationDraft, workspaceSessionTool, workspaceThreadKey, workspaceErrorMessage } from "./workspaceChatLogic"
const state: WorkspaceState = { language: "sv", knowledge_scope: "workspace", view: "relations", documents: [{ source_id: "first", page: 3, zoom: 1.5 }, { source_id: "second", page: 7, zoom: 0.8 }], split_source_ids: ["first", "second"], research_attempt_ids: [], selection: { node_id: "event" } }
const message: WorkspaceMessage = { id: 10, role: "agent", content: "The complete response", session_id: "session-a", event_key: "agent:4", created_at: "2026-10-04T12:00:00Z" }
describe("workspace conversation state", () => {
  it("treats an unchanged document as the same content across revisions", () => {
    const document = { title: "Brev", content: { blocks: [{ id: "p1", text: "Oförändrad" }] } }
    expect(sameArtifactContent(document, { title: document.title, content: document.content })).toBe(true)
    expect(sameArtifactContent(document, { title: "Annat", content: document.content })).toBe(false)
  })
  it("retries a workspace view against the current revision", async () => {
    const latest = { revision: 4, state: { ...state, view: "documents" as const } }
    const calls: number[] = []
    const saved = await commitWorkspaceState({ revision: 2, state }, (value) => ({ ...value, view: "evidence" }), {
      write: async (revision, next) => { calls.push(revision); if (revision === 2) throw new ApiError("workspace_revision_conflict", { status: 409 }); return { revision: revision + 1, state: next } },
      read: async () => latest,
    })
    expect(calls).toEqual([2, 4])
    expect(saved).toEqual({ revision: 5, state: { ...latest.state, view: "evidence" } })
  })
  it("adopts the newer revision when the view is already saved", async () => {
    const latest = { revision: 4, state: { ...state, view: "documents" as const } }
    const saved = await commitWorkspaceState({ revision: 2, state }, (value) => ({ ...value, view: "documents" }), {
      write: async () => { throw new ApiError("workspace_revision_conflict", { status: 409 }) },
      read: async () => latest,
    })
    expect(saved).toBe(latest)
  })
  it("treats a repeated view as the same workspace state", () => {
    expect(sameWorkspaceState(state, { ...state, view: "relations" })).toBe(true)
    expect(sameWorkspaceState(state, { ...state, view: "documents" })).toBe(false)
  })
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
    expect(workspaceErrorMessage(new ApiError("workspace_source_changed_during_search", { status: 409 }), translate)).toBe("voiceWorkspaceChat.stale")
    expect(workspaceErrorMessage(new ApiError("workspace_source_changed_during_read", { status: 409 }), translate)).toBe("voiceWorkspaceChat.sourceReread")
    expect(isWorkspaceSourceReread(new ApiError("workspace_source_changed_during_read", { status: 409 }))).toBe(true)
    expect(workspaceErrorMessage(new ApiError("workspace_revision_conflict", { status: 409 }), translate)).toBe("voiceWorkspaceChat.viewConflict")
    expect(workspaceErrorMessage(new ApiError("private_document_requires_workspace", { status: 409 }), translate)).toBe("voiceWorkspaceChat.privateDocumentScope")
  })
  it("distinguishes unverified passages and source bindings from a changed source version", () => {
    const translate = (key: string) => key
    expect(workspaceErrorMessage(new ApiError("selection_anchor_stale", { status: 409 }), translate)).toBe("voiceWorkspaceChat.selectionUnverified")
    expect(workspaceErrorMessage(new ApiError("source_excerpt_stale", { status: 409 }), translate)).toBe("voiceWorkspaceChat.sourceExcerptUnverified")
    expect(workspaceErrorMessage(new ApiError("document_anchor_source_conflict", { status: 409 }), translate)).toBe("voiceWorkspaceChat.presentationError")
    expect(workspaceErrorMessage(new ApiError("unrecognized_stale_error", { status: 503 }), translate)).toBe("voiceWorkspaceChat.operationError")
  })
  it("reserves the missing-citation message for a source that is not in the workspace", () => {
    const translate = (key: string) => key
    expect(workspaceErrorMessage(new ApiError("workspace_reference_not_found", { status: 404 }), translate)).toBe("voiceWorkspaceChat.referenceUnavailable")
    expect(workspaceErrorMessage(new ApiError("workspace_source_not_found", { status: 404 }), translate)).toBe("voiceWorkspaceChat.referenceUnavailable")
    expect(workspaceErrorMessage(new ApiError("workspace_conversation_not_found", { status: 404 }), translate, "voiceWorkspaceChat.sessionError")).toBe("voiceWorkspaceChat.sessionError")
    expect(workspaceErrorMessage(new ApiError("workspace_not_found", { status: 404 }), translate, "sme.loadError")).toBe("sme.loadError")
  })
  it("isolates drafts for the same expert in different workspaces", () => {
    expect(workspaceThreadKey("workspace-a", "expert", "same-expert")).not.toBe(workspaceThreadKey("workspace-b", "expert", "same-expert"))
    expect(workspaceThreadKey("workspace-a", "expert", "same-expert")).not.toBe(workspaceThreadKey("workspace-a", "panel", "same-expert"))
  })
  it("keeps voice history and replaces a local draft with the expert reply", () => {
    const interview = interviewTranscriptMessage({ id: 4, role: "assistant", content: "Svar", created_at: "2026-10-04T11:00:00Z" })
    const pendingVoice = { ...message, id: -2, event_key: "agent:pending" }
    expect(interview.role).toBe("agent")
    expect(mergeTranscript([message, pendingVoice, { ...message, id: -1, session_id: "local", event_key: "local" }], [interview])).toEqual([pendingVoice, interview, message])
  })
  it("drops a spoken echo once the same reply is in the transcript", () => {
    const spoken = { ...message, id: -8, content: "Jag hänger här med dig.", session_id: "live-speech", event_key: "live-speech:a" }
    const opening = { ...message, id: -9, content: "Hej igen.", session_id: "live-speech", event_key: "live-speech:opening" }
    const stored = interviewTranscriptMessage({ id: 20, role: "assistant", content: "Jag hänger här med dig.", created_at: "2026-10-04T11:00:00Z" })
    const followup = interviewTranscriptMessage({ id: 21, role: "assistant", content: "En annan mening.", created_at: "2026-10-04T11:00:01Z" })
    expect(mergeTranscript([opening, spoken], [stored, followup])).toEqual([opening, stored, followup])
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
  it("returns a tool failure the model can explain instead of a rejected client call", () => {
    expect(JSON.parse(clientToolFailure(new ApiError("workspace_source_not_found", { status: 404 })))).toEqual({
      status: "failed",
      error: "workspace_source_not_found",
    })
  })
  it("runs live-voice company tools through the workspace expert tool", () => {
    expect(expertProxyToolNames).toContain("search_companies")
    expect(workspaceSessionTool("search_companies", { query: "Spotify" })).toEqual({
      endpoint: "expert_tool",
      arguments: { name: "search_companies", arguments: { query: "Spotify" } },
    })
    expect(workspaceSessionTool("show_document", { reference_id: "ref-a" })).toEqual({
      endpoint: "show_document",
      arguments: { reference_id: "ref-a" },
    })
  })
  it("rejects malformed native tool JSON before executing a UI operation", () => {
    expect(clientArguments({ arguments_json: '{"reference_id":"ref-a"}' })).toEqual({ reference_id: "ref-a" })
    expect(() => clientArguments({ arguments_json: "[]" })).toThrow()
    expect(() => clientArguments({ arguments_json: "{" })).toThrow()
  })
  it("signals a ready document artifact once the documents view is showing it", () => {
    const artifact = { id: "draft-a", kind: "document", status: "ready", revision: 1 }
    expect(artifactPresentationKey(artifact, "documents")).toBe("artifact:draft-a:1")
    expect(artifactPresentationKey(artifact, "comparison")).toBeNull()
    expect(artifactPresentationKey({ ...artifact, status: "running" }, "documents")).toBeNull()
  })
  it("reads the generated draft from a succeeded workspace job", () => {
    expect(workspaceGenerationDraft({
      kind: "workspace_generation",
      status: "succeeded",
      request: { artifact_id: "draft-a", voice_workspace_id: "canvas-a" },
      result: { artifact_id: "draft-a" },
    })).toEqual({ artifactId: "draft-a", workspaceId: "canvas-a" })
    expect(workspaceGenerationDraft({
      kind: "workspace_generation",
      status: "running",
      request: { artifact_id: "draft-a", voice_workspace_id: "canvas-a" },
      result: null,
    })).toBeNull()
  })
  it("opens a generation draft only after the job succeeds and the artifact is ready", () => {
    const job = {
      id: "job-a",
      kind: "workspace_generation",
      status: "running",
      request: { artifact_id: "draft-a", voice_workspace_id: "canvas-a" },
      result: null,
    }
    const previousStatus = new Map<string, string>()
    const pending = new Set<string>()
    const opened = new Set<string>()
    expect(takeReadyGenerationArtifact({
      jobs: [job], artifacts: [{ id: "draft-a", status: "running" }], workspaceId: "canvas-a",
      previousStatus, pending, opened,
    })).toBeNull()
    expect(takeReadyGenerationArtifact({
      jobs: [{ ...job, status: "succeeded", result: { artifact_id: "draft-a" } }],
      artifacts: [{ id: "draft-a", status: "running" }], workspaceId: "canvas-a",
      previousStatus, pending, opened,
    })).toBeNull()
    expect(takeReadyGenerationArtifact({
      jobs: [{ ...job, status: "succeeded", result: { artifact_id: "draft-a" } }],
      artifacts: [{ id: "draft-a", status: "ready" }], workspaceId: "canvas-a",
      previousStatus, pending, opened,
    })).toBe("draft-a")
    expect(takeReadyGenerationArtifact({
      jobs: [{ ...job, status: "succeeded", result: { artifact_id: "draft-a" } }],
      artifacts: [{ id: "draft-a", status: "ready" }], workspaceId: "canvas-a",
      previousStatus, pending, opened,
    })).toBeNull()
  })
})
