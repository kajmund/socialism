import type { UnderlagFile } from "@/api/underlag"

/** Selectable once stored — text is extracted later when experts need it. */
export function canUseUnderlag(file: UnderlagFile): boolean {
  const status = file.extraction_status
  if (status === "failed" || status === "empty" || status === "unsupported") {
    return false
  }
  const type = (file.content_type || "").toLowerCase()
  return (
    type === "application/pdf" ||
    type === "text/plain" ||
    type === "text/markdown" ||
    type.includes("wordprocessingml")
  )
}
