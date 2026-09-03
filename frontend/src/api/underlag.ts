import { api } from "@/lib/api"

export type UnderlagExtractionStatus = "ok" | "failed" | "empty" | "unsupported"

export type UnderlagFile = {
  id: string
  kind: string
  filename: string
  content_type: string
  size_bytes: number
  module: string
  owner_user_id: string | null
  extraction_status: UnderlagExtractionStatus | null
  extracted_text?: string | null
  created_at: string
}

export function listUnderlag(module: string): Promise<UnderlagFile[]> {
  return api.get<UnderlagFile[]>("/underlag", { module })
}

export function uploadUnderlag(file: File, module: string): Promise<UnderlagFile> {
  const form = new FormData()
  form.append("file", file)
  return api.postForm<UnderlagFile>(`/underlag?module=${encodeURIComponent(module)}`, form, {
    timeoutMs: 120_000,
  })
}

export function getUnderlag(id: string): Promise<UnderlagFile> {
  return api.get<UnderlagFile>(`/underlag/${id}`)
}
