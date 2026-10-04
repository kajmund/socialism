import type { Job } from "@/api/jobs"
import type { UnderlagFile } from "@/api/underlag"
import { api } from "@/lib/api"

export type Workspace = {
  id: string
  customer_id: number
  name: string
  kind: "company" | "client"
}

export type WorkspaceChatMessage = {
  id: number
  role: "user" | "assistant"
  content: string
  attachment_object_id?: string | null
  job_id?: string | null
  created_at: string
}

export type WorkspaceChat = {
  id: string
  workspace_id: string
  customer_id: number
  persona_id: string | null
  title: string
  messages: WorkspaceChatMessage[]
}

export type WorkspaceFile = UnderlagFile & { workspace_id: string }
export type WorkspaceCitation = {
  label: string
  title?: string | null
  source_object_id?: string | null
  document_version_id?: string | null
  text_unit_id?: string | null
  locator?: string | null
  excerpt: string
  source_url?: string | null
  workspace_id?: string | null
}
export type WorkspaceResearchResult = {
  answer?: string
  citations?: WorkspaceCitation[]
  evidence_set_id?: string
  attempt_id?: string
  run_id?: string
}
export type WorkspaceResearchJob = Omit<Job, "result"> & {
  result: WorkspaceResearchResult | null
}
export type WorkspacePassage = {
  filename?: string
  title?: string
  text?: string
  excerpt?: string
  locator?: string | null
  document_version_id?: string
  text_unit_id?: string
}

function customerQuery(customerId?: number): string {
  return customerId == null ? "" : `?customer_id=${customerId}`
}

export function listWorkspaces(customerId?: number): Promise<Workspace[]> {
  return api.get("/workspaces", { customer_id: customerId })
}

export function createClientWorkspace(name: string, customerId?: number): Promise<Workspace> {
  return api.post(`/workspaces${customerQuery(customerId)}`, { name, kind: "client" })
}

export function listWorkspaceChats(workspaceId: string, customerId?: number): Promise<WorkspaceChat[]> {
  return api.get("/workspace-chats", { workspace_id: workspaceId, customer_id: customerId })
}

export function createWorkspaceChat(workspaceId?: string, personaId?: string, customerId?: number): Promise<WorkspaceChat> {
  return api.post(`/workspace-chats${customerQuery(customerId)}`, {
    workspace_id: workspaceId,
    persona_id: personaId,
  })
}

export function getWorkspaceChat(chatId: string, customerId?: number): Promise<WorkspaceChat> {
  return api.get(`/workspace-chats/${chatId}`, { customer_id: customerId })
}

export function sendWorkspaceMessage(chatId: string, content: string, customerId?: number): Promise<WorkspaceChat> {
  return api.post(`/workspace-chats/${chatId}/messages${customerQuery(customerId)}`, { content }, { timeoutMs: 120_000 })
}

export function listWorkspaceFiles(chatId: string, customerId?: number): Promise<WorkspaceFile[]> {
  return api.get(`/workspace-chats/${chatId}/files`, { customer_id: customerId })
}

export function uploadWorkspaceFile(chatId: string, file: File, customerId?: number): Promise<WorkspaceFile> {
  const form = new FormData()
  form.append("file", file)
  return api.postForm(`/workspace-chats/${chatId}/files${customerQuery(customerId)}`, form, { timeoutMs: 120_000 })
}

export function listWorkspaceResearch(chatId: string, customerId?: number): Promise<WorkspaceResearchJob[]> {
  return api.get(`/workspace-chats/${chatId}/research`, { customer_id: customerId })
}

export function startWorkspaceResearch(chatId: string, question: string, sourceObjectIds: string[], customerId?: number): Promise<WorkspaceResearchJob> {
  return api.post(`/workspace-chats/${chatId}/research${customerQuery(customerId)}`, {
    question,
    source_object_ids: sourceObjectIds,
    entrypoint: "modal",
  })
}

export function getWorkspacePassage(chatId: string, citation: WorkspaceCitation, customerId?: number): Promise<WorkspacePassage> {
  return api.get(`/workspace-chats/${chatId}/sources/${citation.source_object_id}`, {
    customer_id: customerId,
    document_version_id: citation.document_version_id,
    text_unit_id: citation.text_unit_id,
  })
}
