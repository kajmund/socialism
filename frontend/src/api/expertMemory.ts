import { api } from "@/lib/api"

export type ExpertMemory = {
  id: string
  text: string
  source: string
  expert_id: string
  expert_name: string
  persona_id: string | null
  customer_id: number | null
  created_at: string
  updated_at: string
  event: string
  image_sha256: string | null
}

export type ExpertMemoryExpert = {
  expert_id: string
  name: string
  persona_id: string | null
  customer_id: number
}

export type ExpertMemoryList = {
  customer_id: number | null
  count: number
  memories: ExpertMemory[]
  experts?: ExpertMemoryExpert[]
}

export function listExpertMemories(params?: {
  customer_id?: number
  expert_id?: string
}): Promise<ExpertMemoryList> {
  return api.get<ExpertMemoryList>("/expert-memory", params)
}

function personaMemoryPath(personaId: string, memoryId?: string, workspaceId?: string): string {
  const path = `/personas/${personaId}/memories${memoryId ? `/${memoryId}` : ""}`
  return workspaceId ? `${path}?${new URLSearchParams({ workspace_id: workspaceId })}` : path
}

export function listPersonaMemories(personaId: string, workspaceId?: string): Promise<ExpertMemoryList> {
  return api.get<ExpertMemoryList>(personaMemoryPath(personaId, undefined, workspaceId))
}

export function updateExpertMemory(memoryId: string, text: string): Promise<ExpertMemory> {
  return api.patch<ExpertMemory>(`/expert-memory/${memoryId}`, { text })
}

export function deleteExpertMemory(memoryId: string): Promise<void> {
  return api.delete(`/expert-memory/${memoryId}`)
}

export function updatePersonaMemory(
  personaId: string,
  memoryId: string,
  text: string,
  workspaceId?: string,
): Promise<ExpertMemory> {
  return api.patch<ExpertMemory>(personaMemoryPath(personaId, memoryId, workspaceId), { text })
}

export function deletePersonaMemory(personaId: string, memoryId: string, workspaceId?: string): Promise<void> {
  return api.delete(personaMemoryPath(personaId, memoryId, workspaceId))
}

export function clearExpertMemories(params?: {
  customer_id?: number
  expert_id?: string
}): Promise<void> {
  return api.delete("/expert-memory", params)
}

export function clearPersonaMemories(personaId: string, workspaceId?: string): Promise<void> {
  return api.delete(personaMemoryPath(personaId, undefined, workspaceId))
}
