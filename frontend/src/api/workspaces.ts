import { api } from "@/lib/api"
import type { DocumentKnowledgeAnchor, UnderlagFile } from "@/api/underlag"
import type { SpindoctorChartType } from "@/api/spindoctorWidgets"

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
export type WorkspaceResearch = { attempt_id: string; run_id: string; status: string; progress_url: string }
export type WorkspaceSummary = Pick<Workspace, "id" | "title" | "module" | "revision" | "state">
export type Workspace = {
  id: string
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

export const workspaces = {
  list: () => api.get<WorkspaceSummary[]>("/workspaces"),
  create: (title: string, language: "sv" | "en") => api.post<Workspace>("/workspaces", { title, module: "dd", language, idempotency_key: crypto.randomUUID() }),
  get: (id: string) => api.get<Workspace>(`/workspaces/${id}`),
  update: (id: string, expectedRevision: number, state: WorkspaceState) => api.patch<Workspace>(`/workspaces/${id}`, { expected_revision: expectedRevision, state, idempotency_key: crypto.randomUUID() }),
  attach: (id: string, sourceId: string) => api.post<ToolResult>(`/workspaces/${id}/sources`, { source_id: sourceId, idempotency_key: crypto.randomUUID() }),
  upload: (id: string, file: File) => { const form = new FormData(); form.append("file", file); form.append("idempotency_key", crypto.randomUUID()); return api.postForm<ToolResult>(`/workspaces/${id}/sources/upload`, form, { timeoutMs: 120_000 }) },
  reference: (id: string, referenceId: string) => api.get<SourceReference>(`/workspaces/${id}/references/${referenceId}`),
  tool: (id: string, name: string, args: Record<string, unknown>, expectedRevision?: number) => api.post<ToolResult>(`/workspaces/${id}/tools/${name}`, { idempotency_key: crypto.randomUUID(), expected_revision: expectedRevision, arguments: args }),
  artifact: async (id: string, artifactId: string, revision?: number) => { const artifact = await api.get<WorkspaceArtifact>(`/workspaces/${id}/artifacts/${artifactId}`); if (revision == null) return artifact; const historical = await api.get<Pick<WorkspaceArtifact, "revision" | "title" | "content">>(`/workspaces/${id}/artifacts/${artifactId}/revisions/${revision}`); return { ...artifact, ...historical } },
  saveArtifact: async (id: string, artifact: WorkspaceArtifact) => { const result = await api.patch<ToolResult>(`/workspaces/${id}/artifacts/${artifact.id}`, { expected_revision: artifact.revision, title: artifact.title, content: artifact.content, idempotency_key: crypto.randomUUID() }); if (!result.artifact) throw new Error("Missing saved artifact"); return result.artifact },
  export: (id: string, artifactId: string, format: "pdf" | "docx", revision: number) => api.getBlob(`/workspaces/${id}/artifacts/${artifactId}/exports/${format}?revision=${revision}`),
  messages: (id: string, expertId: string) => api.get<{ messages: WorkspaceMessage[] }>(`/workspace-chat/${id}/threads/${expertId}/messages`),
  start: (id: string, expertId: string, mode: "text" | "voice", language: string) => api.post<ChatSession>(`/workspace-chat/${id}/sessions`, { expert_id: expertId, mode, language }),
  sessionTool: (id: string, sessionId: string, name: string, conversationId: string, agentTurn: number, turnEventKey: string | null, args: Record<string, unknown>) => api.post<ToolResult>(`/workspace-chat/${id}/sessions/${sessionId}/tools/${name}`, { conversation_id: conversationId, agent_turn: agentTurn, turn_event_key: turnEventKey, arguments_json: JSON.stringify(args) }),
  bind: (id: string, sessionId: string, conversationId: string) => api.post(`/workspace-chat/${id}/sessions/${sessionId}/bind`, { conversation_id: conversationId }),
  end: (id: string, sessionId: string) => api.delete(`/workspace-chat/${id}/sessions/${sessionId}`),
  event: (id: string, sessionId: string, event: { event_key: string; kind: "user" | "agent" | "correction" | "complete"; text: string; original_event_key?: string; workspace_revision?: number; context_snapshot?: WorkspaceState }) => api.post<{ message_id: number; duplicate: boolean; context?: string }>(`/workspace-chat/${id}/sessions/${sessionId}/events`, event),
}
