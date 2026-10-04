import { ApiError } from "@/lib/http"
import type { MessageKey } from "@/i18n"
import type { WorkspaceMessage, WorkspaceState } from "@/api/voiceWorkspaces"

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

export function workspaceErrorMessage(error: unknown, t: (key: MessageKey) => string, fallback: MessageKey = "voiceWorkspaceChat.operationError"): string {
  const message = error instanceof Error ? error.message : ""
  if (/stale|source_version|anchor_source_conflict/.test(message)) return t("voiceWorkspaceChat.stale")
  if (error instanceof ApiError) {
    if (error.status === 409) return t("voiceWorkspaceChat.conflict")
    if (error.status === 404) return t("voiceWorkspaceChat.referenceUnavailable")
    return t(fallback)
  }
  if (!message || /^(?:[a-z0-9]+_[a-z0-9_]+|HTTP \d|Invalid tool|Missing |Network request|Request timed)/.test(message)) return t(fallback)
  return message
}
