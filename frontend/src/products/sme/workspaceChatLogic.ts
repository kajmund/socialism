import { ApiError } from "@/lib/http"
import type { MessageKey } from "@/i18n"
import type { WorkspaceMessage, WorkspaceState } from "@/api/voiceWorkspaces"
import { EXPERT_TOOL_IDS } from "@/data/expert-tools"

export function isCurrentConversation(expectedGeneration: number, currentGeneration: number, expected: { workspaceId: string | null; expertId: string | null }, current: { workspaceId: string | null; expertId: string | null }): boolean {
  return expectedGeneration === currentGeneration && expected.workspaceId === current.workspaceId && expected.expertId === current.expertId
}

export function interviewTranscriptMessage(message: { id: number; role: "user" | "assistant"; content: string; created_at: string }): WorkspaceMessage {
  return { id: message.id, role: message.role === "user" ? "user" : "agent", content: message.content, created_at: message.created_at, event_key: `interview:${message.id}`, session_id: "interview" }
}

export function mergeTranscript(current: WorkspaceMessage[], incoming: WorkspaceMessage[]): WorkspaceMessage[] {
  const rows = new Map<number, WorkspaceMessage>()
  for (const row of current) if (row.session_id !== "local") rows.set(row.id, row)
  for (const row of incoming) if (row.id > 0) rows.set(row.id, row)
  return [...rows.values()].sort((left, right) => left.id - right.id)
}

export function upsertTranscript(messages: WorkspaceMessage[], message: WorkspaceMessage): WorkspaceMessage[] {
  const index = messages.findIndex((row) => row.session_id === message.session_id && row.event_key === message.event_key)
  if (index < 0) return [...messages, message]
  return messages.map((row, i) => i === index ? message : row)
}

export function openWorkspaceDocument(state: WorkspaceState, sourceId: string, page = 1): WorkspaceState {
  const current = state.documents.find((document) => document.source_id === sourceId)
  const document = { source_id: sourceId, page, zoom: current?.zoom ?? 1 }
  const split = state.split_source_ids.length === 2 && !state.split_source_ids.includes(sourceId) ? [sourceId, state.split_source_ids[0]] : state.split_source_ids
  return { ...state, view: "documents", split_source_ids: split, documents: [document, ...state.documents.filter((row) => row.source_id !== sourceId)] }
}

export const workspaceClientToolNames = ["open_ingest_picker", "show_evidence", "show_document", "focus_anchor", "show_comparison", "show_relations", "show_knowledge", "show_artifact"] as const
export const workspaceServerToolNames = ["get_workspace_context", "ingest_source", "get_job_status", "search_knowledge", "read_source", "start_research", "compare_sources", "get_relations", "render_chart", "create_document", "revise_document", "export_document", "expert_tool"] as const
const workspaceToolNames = new Set<string>([...workspaceClientToolNames, ...workspaceServerToolNames])
// The shared ElevenLabs agent also carries live-voice tools such as search_companies.
// The SDK rejects a client tool call unless that exact name is registered here.
export const expertProxyToolNames = EXPERT_TOOL_IDS.filter((name) => !workspaceToolNames.has(name))

export function isWorkspaceServerTool(name: string): boolean {
  return (workspaceServerToolNames as readonly string[]).includes(name)
}

export function workspaceSessionTool(name: string, args: Record<string, unknown>): { endpoint: string; arguments: Record<string, unknown> } {
  if ((expertProxyToolNames as readonly string[]).includes(name)) {
    return { endpoint: "expert_tool", arguments: { name, arguments: args } }
  }
  return { endpoint: name, arguments: args }
}

export function clientArguments(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid tool parameters")
  const record = raw as Record<string, unknown>
  if (typeof record.arguments_json !== "string") return record
  const parsed: unknown = JSON.parse(record.arguments_json)
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid tool parameters")
  return parsed as Record<string, unknown>
}

export function requiredString(args: Record<string, unknown>, key: string): string {
  if (typeof args[key] !== "string" || !args[key]) throw new Error(`Missing ${key}`)
  return args[key]
}

export function workspaceThreadKey(workspaceId: string, threadType: string, threadId: string): string {
  return JSON.stringify([workspaceId, threadType, threadId])
}

export function sameWorkspaceState(left: WorkspaceState, right: WorkspaceState): boolean {
  return sameValue(left, right)
}

export function sameArtifactContent(left: { title: string; content: unknown }, right: { title: string; content: unknown }): boolean {
  return sameValue(left.title, right.title) && sameValue(left.content, right.content)
}

export async function commitWorkspaceState<T extends { revision: number; state: WorkspaceState }>(current: T, update: (state: WorkspaceState) => WorkspaceState, io: { write: (revision: number, state: WorkspaceState) => Promise<T>; read: () => Promise<T> }): Promise<T> {
  const next = update(current.state)
  if (sameWorkspaceState(current.state, next)) return current
  try {
    return await io.write(current.revision, next)
  } catch (error) {
    if (!(error instanceof ApiError) || error.message !== "workspace_revision_conflict") throw error
    const latest = await io.read()
    const retried = update(latest.state)
    if (sameWorkspaceState(latest.state, retried)) return latest
    return await io.write(latest.revision, retried)
  }
}

function sameValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((item, index) => sameValue(item, right[index]))
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const key of keys) if (!sameValue(a[key], b[key])) return false
  return true
}

export function isWorkspaceSourceReread(error: unknown): boolean {
  return error instanceof ApiError && error.message === "workspace_source_changed_during_read"
}

export function clientToolFailure(error: unknown): string {
  const message = error instanceof Error && error.message ? error.message : "tool_failed"
  return JSON.stringify({ status: "failed", error: message })
}

const missingWorkspaceReference = new Set([
  "workspace_reference_not_found",
  "workspace_evidence_not_found",
  "workspace_graph_source_not_found",
  "workspace_source_not_found",
  "workspace_selection_not_found",
])

export function workspaceErrorMessage(error: unknown, t: (key: MessageKey) => string, fallback: MessageKey = "voiceWorkspaceChat.operationError"): string {
  const message = error instanceof Error ? error.message : ""
  if (message === "private_document_requires_workspace") return t("voiceWorkspaceChat.privateDocumentScope")
  if (message === "workspace_source_version_missing" || message === "workspace_source_file_hash_missing" || message === "selection_source_version_required") return t("voiceWorkspaceChat.sourceVersionMissing")
  if (message === "selection_anchor_stale") return t("voiceWorkspaceChat.selectionUnverified")
  if (message === "source_excerpt_stale") return t("voiceWorkspaceChat.sourceExcerptUnverified")
  if (message === "document_anchor_source_conflict") return t("voiceWorkspaceChat.presentationError")
  if (message === "workspace_reference_stale" || message === "workspace_source_changed_during_search") return t("voiceWorkspaceChat.stale")
  if (message === "workspace_source_changed_during_read") return t("voiceWorkspaceChat.sourceReread")
  if (message === "workspace_revision_conflict") return t("voiceWorkspaceChat.viewConflict")
  if (error instanceof ApiError) {
    if (error.status === 409) return t("voiceWorkspaceChat.conflict")
    if (error.status === 404 && missingWorkspaceReference.has(error.message)) return t("voiceWorkspaceChat.referenceUnavailable")
    return t(fallback)
  }
  if (!message || /^(?:[a-z0-9]+_[a-z0-9_]+|HTTP \d|Invalid tool|Missing |Network request|Request timed)/.test(message)) return t(fallback)
  return message
}

export function workspaceGenerationDraft(job: {
  kind: string
  status: string
  request: Record<string, unknown>
  result?: { artifact_id?: string } | null
}): { artifactId: string; workspaceId: string } | null {
  if (job.kind !== "workspace_generation" || job.status !== "succeeded") return null
  const artifactId = typeof job.request.artifact_id === "string" && job.request.artifact_id
    ? job.request.artifact_id
    : typeof job.result?.artifact_id === "string" && job.result.artifact_id
      ? job.result.artifact_id
      : ""
  const workspaceId = typeof job.request.voice_workspace_id === "string" ? job.request.voice_workspace_id : ""
  if (!artifactId || !workspaceId) return null
  return { artifactId, workspaceId }
}

export function artifactPresentationKey(artifact: { id: string; kind: string; status: string; revision: number } | undefined, view: WorkspaceState["view"]): string | null {
  if (!artifact || artifact.status !== "ready") return null
  const shown = (view === "documents" && (artifact.kind === "document" || artifact.kind === "chart"))
    || (view === "comparison" && artifact.kind === "comparison")
    || (view === "relations" && artifact.kind === "relations")
  return shown ? `artifact:${artifact.id}:${artifact.revision}` : null
}

export function takeReadyGenerationArtifact(input: {
  jobs: Array<{ id: string; kind: string; status: string; request: Record<string, unknown>; result?: { artifact_id?: string } | null }>
  artifacts: Array<{ id: string; status: string }>
  workspaceId: string | null | undefined
  previousStatus: Map<string, string>
  pending: Set<string>
  opened: Set<string>
}): string | null {
  for (const job of input.jobs) {
    const previous = input.previousStatus.get(job.id)
    if (previous != null && previous !== "succeeded" && job.status === "succeeded") input.pending.add(job.id)
    input.previousStatus.set(job.id, job.status)
  }
  if (!input.workspaceId) return null
  for (const jobId of input.pending) {
    if (input.opened.has(jobId)) continue
    const job = input.jobs.find((row) => row.id === jobId)
    if (!job) continue
    const draft = workspaceGenerationDraft(job)
    if (!draft || draft.workspaceId !== input.workspaceId) continue
    if (!input.artifacts.some((row) => row.id === draft.artifactId && row.status === "ready")) continue
    input.opened.add(jobId)
    input.pending.delete(jobId)
    return draft.artifactId
  }
  return null
}
