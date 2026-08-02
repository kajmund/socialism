import { api } from "@/lib/api"

export type MessageType = "post" | "news"
export type MessageVariantKey = "analytical" | "narrative" | "concise"

export type Message = {
  id: string
  type: MessageType
  title: string
  body: string
  source_url: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type MessageWrite = {
  id?: string
  type: MessageType
  title: string
  body: string
  source_url?: string | null
  metadata?: Record<string, unknown>
}

export type MessageVariant = {
  key: MessageVariantKey
  label: string
  body: string
}

export type GenerateVariantsRequest = {
  type: MessageType
  raw_text?: string
  source_url?: string | null
  audience?: string
  purpose?: string
  tone?: string
}

export function listMessages(params?: {
  q?: string
  type?: MessageType
}): Promise<Message[]> {
  return api.get<Message[]>("/messages", params)
}

export function getMessage(id: string): Promise<Message> {
  return api.get<Message>(`/messages/${id}`)
}

export function createMessage(body: MessageWrite): Promise<Message> {
  return api.post<Message>("/messages", body)
}

export function updateMessage(
  id: string,
  body: Partial<MessageWrite>,
): Promise<Message> {
  return api.patch<Message>(`/messages/${id}`, body)
}

export function deleteMessage(id: string): Promise<void> {
  return api.delete(`/messages/${id}`)
}

export function summarizeUrl(body: {
  url: string
  message_type?: MessageType
}): Promise<{ summary: string; source_url: string; source_domain: string }> {
  return api.post("/messages/summarize-url", body, { timeoutMs: 60_000 })
}

export function generateVariants(
  body: GenerateVariantsRequest,
): Promise<{ variants: MessageVariant[] }> {
  return api.post("/messages/generate-variants", body, { timeoutMs: 120_000 })
}

/** Map run injection type → library Message type for filtering. */
export function libraryTypeForInjection(
  injectionType: "party_post" | "news_post" | "ad_post",
): MessageType {
  return injectionType === "news_post" ? "news" : "post"
}
