export type SourceKindFile = {
  content_type?: string | null
  filename?: string | null
}

const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

export function isPdfSource(file: SourceKindFile | null | undefined): boolean {
  if (!file) return false
  const type = (file.content_type ?? "").toLowerCase()
  const name = (file.filename ?? "").toLowerCase()
  return type === "application/pdf" || name.endsWith(".pdf")
}

export function isDocxSource(file: SourceKindFile | null | undefined): boolean {
  if (!file) return false
  const type = (file.content_type ?? "").toLowerCase()
  const name = (file.filename ?? "").toLowerCase()
  return type === DOCX_TYPE || type.includes("wordprocessingml") || name.endsWith(".docx")
}
