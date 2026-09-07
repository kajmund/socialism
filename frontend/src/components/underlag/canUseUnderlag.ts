import type { UnderlagFile } from "@/api/underlag"

export function canUseUnderlag(file: UnderlagFile): boolean {
  return file.extraction_status === "ok" && Boolean(file.extracted_text?.trim())
}
