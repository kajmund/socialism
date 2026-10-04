import type { WorkspaceFile } from "@/api/workspaces"

export type FileState = "uploaded" | "ingesting" | "ready" | "failed"

export function workspaceFileState(file: WorkspaceFile): FileState {
  if (["failed", "empty", "unsupported", "needs_ocr"].includes(file.extraction_status ?? "")) return "failed"
  if (["failed", "partial", "empty", "needs_ocr"].includes(file.knowledge_status ?? "")) return "failed"
  if (file.knowledge_status === "ready") return "ready"
  if (file.knowledge_status === "running") return "ingesting"
  return "uploaded"
}

export function selectedFilesBlocked(files: WorkspaceFile[], selectedIds: string[]): boolean {
  return selectedIds.some((id) => {
    const file = files.find((row) => row.id === id)
    return !file || workspaceFileState(file) !== "ready"
  })
}

export function safeSourceUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : null
  } catch {
    return null
  }
}
