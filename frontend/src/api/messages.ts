import { api } from "@/lib/api"
import { env } from "@/lib/env"
import { OS_DEFAULT_PROJECT_ID } from "@/lib/scoping"

export type MessageType = "post" | "news"
export type MessageVariantKey = "analytical" | "narrative" | "concise"

export type Message = {
  id: string
  type: MessageType
  title: string
  body: string
  source_url: string | null
  metadata: Record<string, unknown>
  image_sha256: string | null
  image_caption: string | null
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
  project_id?: number
}): Promise<Message[]> {
  return api.get<Message[]>("/messages", {
    ...params,
    project_id: params?.project_id ?? OS_DEFAULT_PROJECT_ID,
  })
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

export type ImageCacheEntry = {
  sha256: string
  caption: string
  content_type: string
  size_bytes: number
  vision_provider: string
  vision_model: string
  caption_edited: boolean
  created_at: string
  updated_at: string
}

export type ImageCacheList = {
  cache_dir: string
  count: number
  entries: ImageCacheEntry[]
}

export function listImageCache(): Promise<ImageCacheList> {
  return api.get<ImageCacheList>("/messages/images/cache")
}

export function uploadMessageImage(
  file: File,
  locale: "sv" | "en" = "sv",
): Promise<{ entry: ImageCacheEntry; cache_hit: boolean }> {
  const form = new FormData()
  form.set("image", file)
  form.set("locale", locale)
  return api.postForm("/messages/images/upload", form, { timeoutMs: 120_000 })
}

export function patchMessageImageCaption(
  sha256: string,
  caption: string,
): Promise<ImageCacheEntry> {
  return api.patch<ImageCacheEntry>(`/messages/images/cache/${sha256}`, { caption })
}

export function deleteMessageImageCacheEntry(sha256: string): Promise<{ deleted: boolean }> {
  return api.delete(`/messages/images/cache/${sha256}`)
}

export function cachedImageUrl(sha256: string): string {
  const base = env.apiBaseUrl.replace(/\/$/, "")
  return `${base}/messages/images/cache/${sha256}/file`
}
