import { api } from "@/lib/api"
import type {
  EditablePersona,
  LibraryPersona,
  PersonaOrigin,
} from "@/data/library-types"

export type PersonaDetail = LibraryPersona

export type PersonaWrite = {
  id?: string
  name: string
  age: number
  occ: string
  district: string
  quote?: string
  origin?: PersonaOrigin
  profile?: EditablePersona
}

export function editableToWrite(
  persona: EditablePersona,
  origin: PersonaOrigin = "manuell",
  quote = "",
): PersonaWrite {
  const age = Number.parseInt(persona.age, 10)
  return {
    name: persona.name,
    age: Number.isFinite(age) ? age : 0,
    occ: persona.yrke,
    district: persona.ort,
    quote: quote || persona.ton || "",
    origin,
    profile: persona,
  }
}

export function listPersonas(params?: {
  q?: string
  origin?: string
  exclude_origin?: string
}): Promise<LibraryPersona[]> {
  return api.get<LibraryPersona[]>("/personas", params)
}

/** Default library listing — excludes population-generated personas. */
export function listLibraryPersonas(params?: {
  q?: string
  origin?: string
}): Promise<LibraryPersona[]> {
  if (params?.origin === "population") {
    return listPersonas({ q: params.q, origin: "population" })
  }
  return listPersonas({
    q: params?.q,
    origin: params?.origin,
    exclude_origin: "population",
  })
}

export function getPersona(id: string): Promise<PersonaDetail> {
  return api.get<PersonaDetail>(`/personas/${id}`)
}

export function createPersona(body: PersonaWrite): Promise<PersonaDetail> {
  return api.post<PersonaDetail>("/personas", body)
}

export function updatePersona(
  id: string,
  body: Partial<PersonaWrite>,
): Promise<PersonaDetail> {
  return api.put<PersonaDetail>(`/personas/${id}`, body)
}

export function duplicatePersona(id: string): Promise<PersonaDetail> {
  return api.post<PersonaDetail>(`/personas/${id}/duplicate`)
}

export function deletePersona(id: string): Promise<void> {
  return api.delete(`/personas/${id}`)
}

export type ChatMode = "interview" | "character"

export type PersonaMessage = {
  id: number
  mode: ChatMode
  role: "user" | "assistant"
  content: string
  created_at: string
}

export type PersonaGenerateRequest = {
  mode: "beskrivning" | "demografi"
  freeText?: string
  demografi?: Record<string, string>
  count?: number
}

export type PersonaChatResponse = {
  reply: string
  messages: PersonaMessage[]
  suggestions?: string[]
}

export function generatePersonas(
  body: PersonaGenerateRequest,
): Promise<{ candidates: EditablePersona[] }> {
  return api.post<{ candidates: EditablePersona[] }>("/personas/generate", body)
}

export function listPersonaMessages(
  id: string,
  mode: ChatMode,
): Promise<PersonaMessage[]> {
  return api.get<PersonaMessage[]>(`/personas/${id}/messages`, { mode })
}

export function getSuggestedQuestions(
  id: string,
  mode: ChatMode,
): Promise<{ questions: string[] }> {
  return api.get<{ questions: string[] }>(`/personas/${id}/suggested-questions`, {
    mode,
  })
}

export function chatWithPersona(
  id: string,
  body: { mode: ChatMode; message: string },
): Promise<PersonaChatResponse> {
  return api.post(`/personas/${id}/chat`, body)
}

export function clearPersonaMessages(id: string, mode: ChatMode): Promise<void> {
  return api.delete(`/personas/${id}/messages?mode=${encodeURIComponent(mode)}`)
}

export function deletePersonaMessage(
  id: string,
  messageId: number,
): Promise<{ deleted_ids: number[] }> {
  return api.delete<{ deleted_ids: number[] }>(
    `/personas/${id}/messages/${messageId}`,
  )
}

export function resendPersonaMessage(
  id: string,
  messageId: number,
): Promise<PersonaChatResponse> {
  return api.post(`/personas/${id}/messages/${messageId}/resend`)
}
