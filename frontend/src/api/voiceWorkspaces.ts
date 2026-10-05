import { api } from "@/lib/api"
import type { DocumentKnowledgeAnchor, UnderlagFile } from "@/api/underlag"
import type { SpindoctorChartType } from "@/api/spindoctorWidgets"
import { requireVoiceWorkspace } from "./voiceWorkspaceResponse"

export type KnowledgeScope = "workspace" | "general" | "research"
export type WorkspaceView = "evidence" | "comparison" | "documents" | "relations"
export type SourceReference = {
  reference_id: string
  number: number
  source_id: string
  source_kind: string
  title: string
  excerpt: string
  anchor: DocumentKnowledgeAnchor | null
  source_version: string
  stale: boolean
}
export type WorkspaceSelection = {
  reference_id?: string
  artifact_id?: string
  artifact_revision?: number
  block_id?: string
  node_id?: string
  edge_id?: string
  source_id?: string
  source_version?: string
  source_file_sha256?: string
  anchor?: DocumentKnowledgeAnchor
}
export type WorkspaceState = {
  expert_id?: string | null
  language: "sv" | "en" | "nb"
  knowledge_scope: KnowledgeScope
  view: WorkspaceView
  documents: { source_id: string; page: number; zoom: number; reference_id?: string | null }[]
  split_source_ids: string[]
  active_artifact_id?: string | null
  selection?: WorkspaceSelection | null
  research_attempt_ids: string[]
}
export type ArtifactBlock = { id: string; type: "heading" | "paragraph"; text: string; source_refs: string[] }
export type WorkspaceArtifact = {
  id: string
  title: string
  kind: string
  revision: number
  status: string
  job_id: string | null
  error: string | null
  content: { blocks?: ArtifactBlock[] } & Record<string, unknown>
}
export type WorkspaceResearch = { job_id: string; attempt_id: string | null; run_id: string | null; status: string; progress_url: string }
export type VoiceWorkspaceParent = { workspaceId: string; customerId?: number }
export type WorkspaceSummary = Pick<Workspace, "id" | "workspace_id" | "chat_id" | "customer_id" | "title" | "module" | "revision" | "state">
export type Workspace = {
  id: string
  workspace_id: string
  chat_id: string
  customer_id: number
  title: string
  module: string
  revision: number
  state: WorkspaceState
  sources: UnderlagFile[]
  artifacts: WorkspaceArtifact[]
  references: SourceReference[]
  research: WorkspaceResearch[]
}
export type WorkspaceMessage = {
  id: number
  role: "user" | "agent"
  content: string
  created_at: string
  event_key: string
  session_id: string
}
export type VoiceWorkspaceInboxItem = {
  expert_id: string
  preview: string
  last_message_at: string | null
  unread_count: number
}
export type ChatSession = {
  session_id: string
  generation: number
  connection_type: "websocket" | "webrtc"
  conversation_token: string | null
  signed_url: string | null
  dynamic_variables: Record<string, string | number | boolean>
  context: string
  expires_at: string
}
export type KnowledgeGap = { source_id?: string | null; status: string | null; detail?: string | null }
export type KnowledgeResult = { items: SourceReference[]; gaps: KnowledgeGap[] }
export type Comparison = { title?: string; columns: string[]; rows: { id: string; label: string; cells: { text: string | null; source_refs: string[] }[] }[]; assessment?: string }
export type Relations = {
  title?: string
  nodes: { id: string; label: string; kind: string; description?: string; source_refs: string[] }[]
  edges: { id: string; source: string; target: string; type?: string; label: string; interpretation: boolean; source_refs: string[] }[]
}
export type WorkspaceChart = { title?: string; chart_type: SpindoctorChartType; series: { label: string; value: number }[]; source_refs: string[] }
export type ToolResult = {
  operation_id: string
  status: "completed" | "queued"
  items?: SourceReference[]
  gaps?: KnowledgeGap[]
  stale?: boolean
  reference?: SourceReference
  text?: string
  file_url?: string
  comparison?: Comparison
  relations?: Relations
  chart?: WorkspaceChart
  artifact?: WorkspaceArtifact
  artifact_id?: string
  job_id?: string
  snapshot?: { title: string; excerpt: string; source_url?: string; provenance?: Record<string, unknown> }
  download_url?: string
}

export const voiceWorkspaces = {
  list: (parent: VoiceWorkspaceParent) => api.get<WorkspaceSummary[]>("/voice-workspaces", { workspace_id: parent.workspaceId, customer_id: parent.customerId }),
  create: (title: string, language: "sv" | "en", parent: VoiceWorkspaceParent) => api.post<unknown>(`/voice-workspaces${parent.customerId == null ? "" : `?customer_id=${parent.customerId}`}`, { title, workspace_id: parent.workspaceId, module: "dd", language, idempotency_key: crypto.randomUUID() }).then(requireVoiceWorkspace),
  get: (id: string) => api.get<unknown>(`/voice-workspaces/${id}`).then(requireVoiceWorkspace),
  update: (id: string, expectedRevision: number, state: WorkspaceState) => api.patch<unknown>(`/voice-workspaces/${id}`, { expected_revision: expectedRevision, state, idempotency_key: crypto.randomUUID() }).then(requireVoiceWorkspace),
  attach: (id: string, sourceId: string) => api.post<ToolResult>(`/voice-workspaces/${id}/sources`, { source_id: sourceId, idempotency_key: crypto.randomUUID() }),
  upload: (id: string, file: File) => { const form = new FormData(); form.append("file", file); form.append("idempotency_key", crypto.randomUUID()); return api.postForm<ToolResult>(`/voice-workspaces/${id}/sources/upload`, form, { timeoutMs: 120_000 }) },
  source: (id: string, sourceId: string) => api.get<UnderlagFile & { source_version: string }>(`/voice-workspaces/${id}/sources/${sourceId}`),
  sourceFile: (id: string, sourceId: string) => api.getBlob(`/voice-workspaces/${id}/sources/${sourceId}/file`),
  sourceFileWithVersion: (id: string, sourceId: string) => api.getBlobWithHeaders(`/voice-workspaces/${id}/sources/${sourceId}/file`).then(({ blob, headers }) => ({ blob, sourceVersion: requireSourceVersion(headers.get("X-Workspace-Source-Version")), sourceFileSha256: requireSourceFileSha256(headers.get("X-Workspace-File-Sha256")) })),
  reference: (id: string, referenceId: string) => api.get<SourceReference>(`/voice-workspaces/${id}/references/${referenceId}`),
  tool: (id: string, name: string, args: Record<string, unknown>, expectedRevision?: number) => api.post<ToolResult>(`/voice-workspaces/${id}/tools/${name}`, { idempotency_key: crypto.randomUUID(), expected_revision: expectedRevision, arguments: args }, name === "search_knowledge" ? { timeoutMs: 120_000 } : undefined),
  artifact: async (id: string, artifactId: string, revision?: number) => { const artifact = await api.get<WorkspaceArtifact>(`/voice-workspaces/${id}/artifacts/${artifactId}`); if (revision == null) return artifact; const historical = await api.get<Pick<WorkspaceArtifact, "revision" | "title" | "content">>(`/voice-workspaces/${id}/artifacts/${artifactId}/revisions/${revision}`); return { ...artifact, ...historical } },
  saveArtifact: async (id: string, artifact: WorkspaceArtifact) => { const result = await api.patch<ToolResult>(`/voice-workspaces/${id}/artifacts/${artifact.id}`, { expected_revision: artifact.revision, title: artifact.title, content: artifact.content, idempotency_key: crypto.randomUUID() }); if (!result.artifact) throw new Error("Missing saved artifact"); return result.artifact },
  export: (id: string, artifactId: string, format: "pdf" | "docx", revision: number) => api.getBlob(`/voice-workspaces/${id}/artifacts/${artifactId}/exports/${format}?revision=${revision}`),
  messages: (id: string, expertId: string) => api.get<{ messages: WorkspaceMessage[] }>(`/workspace-chat/${id}/threads/${expertId}/messages`),
  inbox: (id: string) => api.get<VoiceWorkspaceInboxItem[]>(`/voice-workspaces/${id}/inbox`),
  read: (id: string, expertId: string) => api.post<{ last_read_message_id: number | null }>(`/voice-workspaces/${id}/experts/${expertId}/read`),
  start: (id: string, expertId: string, mode: "text" | "voice", language: string) => api.post<ChatSession>(`/workspace-chat/${id}/sessions`, { expert_id: expertId, mode, language }),
  sessionTool: (id: string, sessionId: string, name: string, conversationId: string, agentTurn: number, turnEventKey: string | null, args: Record<string, unknown>) => api.post<ToolResult>(`/workspace-chat/${id}/sessions/${sessionId}/tools/${name}`, { conversation_id: conversationId, agent_turn: agentTurn, turn_event_key: turnEventKey, arguments_json: JSON.stringify(args) }),
  bind: (id: string, sessionId: string, conversationId: string) => api.post(`/workspace-chat/${id}/sessions/${sessionId}/bind`, { conversation_id: conversationId }),
  end: (id: string, sessionId: string) => api.delete(`/workspace-chat/${id}/sessions/${sessionId}`),
  event: (id: string, sessionId: string, event: { event_key: string; kind: "user" | "agent" | "correction" | "complete"; text: string; original_event_key?: string; workspace_revision?: number; context_snapshot?: WorkspaceState }) => api.post<{ message_id: number; duplicate: boolean; context?: string }>(`/workspace-chat/${id}/sessions/${sessionId}/events`, event),
}

export function requireSourceVersion(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) throw new Error("workspace_source_version_missing")
  return value
}

export function requireSourceFileSha256(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) throw new Error("workspace_source_file_hash_missing")
  return value
}
