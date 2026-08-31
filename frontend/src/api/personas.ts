import { api } from "@/lib/api"
import { BOLAG_DEMO_CUSTOMER_ID, OS_CUSTOMER_ID } from "@/lib/scoping"
import type {
  EditablePersona,
  LibraryPersona,
  PersonaKind,
  PersonaOrigin,
} from "@/data/library-types"

export type PersonaDetail = LibraryPersona

export type PersonaWrite = {
  id?: string
  kind?: PersonaKind
  customer_id?: number
  name: string
  age?: number | null
  occ: string
  district: string
  quote?: string
  origin?: PersonaOrigin
  profile?: EditablePersona
  tools?: string[]
}

export type PersonaWriteOptions = {
  kind?: PersonaKind
  customerId?: number
  tools?: string[]
}

export function editableToWrite(
  persona: EditablePersona,
  origin: PersonaOrigin = "manuell",
  quote = "",
  options: PersonaWriteOptions = {},
): PersonaWrite {
  const kind = options.kind ?? "persona"
  if (kind === "expert") {
    const occ =
      persona.yrkesbakgrund && persona.yrkesbakgrund !== "—"
        ? persona.yrkesbakgrund
        : persona.yrke
    return {
      kind: "expert",
      customer_id: options.customerId ?? BOLAG_DEMO_CUSTOMER_ID,
      name: persona.name,
      occ,
      district: persona.ort,
      quote: quote || persona.beskrivning || "",
      origin,
      profile: persona,
      tools: options.tools,
    }
  }
  const age = Number.parseInt(persona.age, 10)
  return {
    kind: "persona",
    customer_id: options.customerId ?? OS_CUSTOMER_ID,
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
  customer_id?: number
  kind?: PersonaKind
}): Promise<LibraryPersona[]> {
  return api.get<LibraryPersona[]>("/personas", params)
}

/** Default library listing — excludes population-generated personas. */
export function listLibraryPersonas(params?: {
  q?: string
  origin?: string
  customer_id?: number
}): Promise<LibraryPersona[]> {
  if (params?.origin === "population") {
    return listPersonas({
      q: params.q,
      origin: "population",
      customer_id: params.customer_id ?? OS_CUSTOMER_ID,
      kind: "persona",
    })
  }
  return listPersonas({
    q: params?.q,
    origin: params?.origin,
    exclude_origin: "population",
    customer_id: params?.customer_id ?? OS_CUSTOMER_ID,
    kind: "persona",
  })
}

export function listExpertPersonas(params?: {
  q?: string
  customer_id?: number
}): Promise<LibraryPersona[]> {
  return listPersonas({
    q: params?.q,
    customer_id: params?.customer_id ?? BOLAG_DEMO_CUSTOMER_ID,
    kind: "expert",
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
