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
  folder_id: string | null
  extraction_status: UnderlagExtractionStatus | null
  extracted_text?: string | null
  created_at: string
}

export type UnderlagFolder = {
  id: string
  name: string
  parent_id: string | null
  created_at: string
}

export type UnderlagListing = {
  folder_id: string | null
  folders: UnderlagFolder[]
  files: UnderlagFile[]
}

export function listUnderlag(module: string, folderId?: string | null): Promise<UnderlagListing> {
  return api.get<UnderlagListing>("/underlag", {
    module,
    folder_id: folderId ?? undefined,
  })
}

export function createUnderlagFolder(body: {
  module: string
  name: string
  parent_id?: string | null
}): Promise<UnderlagFolder> {
  return api.post<UnderlagFolder>("/underlag/folders", {
    module: body.module,
    name: body.name,
    parent_id: body.parent_id ?? null,
  })
}

export function uploadUnderlag(
  file: File,
  module: string,
  folderId?: string | null,
): Promise<UnderlagFile> {
  const form = new FormData()
  form.append("file", file)
  const folderQuery = folderId ? `&folder_id=${encodeURIComponent(folderId)}` : ""
  return api.postForm<UnderlagFile>(
    `/underlag?module=${encodeURIComponent(module)}${folderQuery}`,
    form,
    {
      timeoutMs: 120_000,
    },
  )
}

export function getUnderlag(id: string): Promise<UnderlagFile> {
  return api.get<UnderlagFile>(`/underlag/${id}`)
}
