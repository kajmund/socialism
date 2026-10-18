import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { PassageAuthor, SourceReference, Workspace, WorkspaceState } from "@/api/voiceWorkspaces"
import { pdfAnchorKind, pdfAnchorRectangles } from "@/components/underlag/pdfAnchorPresentation"
import { passageCommentKey } from "./passageCommentKey"

export type DocumentMark = {
  anchor: DocumentKnowledgeAnchor
  authorKind: "user" | "expert" | "passage"
  authorId: string | null
  authorName: string | null
  passageKey: string
}

type MarkReference = Pick<SourceReference, "source_id" | "stale" | "anchor"> & { marked_by?: PassageAuthor | null }

export function clearWorkspaceDocumentSelection(state: WorkspaceState, sourceId: string, references: SourceReference[]): WorkspaceState {
  const document = state.documents.find((row) => row.source_id === sourceId)
  const selectedReferenceId = state.selection?.reference_id
  const selectedSourceId = state.selection?.source_id ?? references.find((row) => row.reference_id === selectedReferenceId)?.source_id
  const clearSelection = selectedSourceId === sourceId || (selectedReferenceId != null && selectedReferenceId === document?.reference_id)
  if (!clearSelection && document?.reference_id == null) return state
  return {
    ...state,
    selection: clearSelection ? null : state.selection,
    documents: state.documents.map((row) => row.source_id === sourceId && row.reference_id != null ? { ...row, reference_id: null } : row),
  }
}

export function markIsLocked(mark: Pick<DocumentMark, "authorKind" | "authorId">, readerId: string | null): boolean {
  if (mark.authorKind === "expert") return true
  return mark.authorKind === "user" && mark.authorId != null && mark.authorId !== readerId
}

export function foreignPassage(marks: DocumentMark[], anchor: DocumentKnowledgeAnchor, sourceId: string, readerId: string | null): DocumentMark | null {
  const key = passageCommentKey(sourceId, anchor)
  const quote = (anchor.exact_text ?? "").replace(/\s/g, "").toLowerCase()
  for (const mark of marks) {
    if (!markIsLocked(mark, readerId)) continue
    if (mark.passageKey === key) return mark
    const page = anchor.page_number
    const samePage = page == null || mark.anchor.page_number == null || mark.anchor.page_number === page
    const marked = (mark.anchor.exact_text ?? "").replace(/\s/g, "").toLowerCase()
    if (samePage && quote.length > 0 && quote === marked) return mark
  }
  return null
}

export function textOccurrenceIndex(text: string, exact: string, prefix: string | null | undefined): number {
  if (!exact) return -1
  const lead = prefix?.trim()
  if (!lead) return text.indexOf(exact)
  const from = text.lastIndexOf(lead)
  if (from < 0) return text.indexOf(exact)
  const at = text.indexOf(exact, from + lead.length)
  return at >= 0 ? at : text.indexOf(exact)
}

export function visibleDocumentMarks(
  references: MarkReference[],
  sourceId: string,
  page: number | null,
  active: DocumentKnowledgeAnchor | null | undefined,
  options: { cleared: boolean; manual: boolean; user: { id: string; name: string } | null; drafts?: DocumentKnowledgeAnchor[] },
): DocumentMark[] {
  const marks: DocumentMark[] = []
  const seen = new Set<string>()
  const add = (mark: Omit<DocumentMark, "passageKey">) => {
    const anchor = mark.anchor
    if (!anchor || (page != null && anchor.page_number !== page)) return
    const rects = pdfAnchorRectangles(anchor)
    if (!rects.length && !anchor.exact_text?.trim()) return
    const owner = `${mark.authorKind ?? ""}:${mark.authorId ?? ""}`
    const key = rects.length
      ? `${owner}:${JSON.stringify(rects.map(({ x, y, width, height }) => [x, y, width, height]))}`
      : `${owner}:text:${anchor.prefix_text ?? ""}:${anchor.exact_text}`
    if (seen.has(key)) return
    seen.add(key)
    marks.push({ ...mark, passageKey: passageCommentKey(sourceId, mark.anchor) })
  }
  const userMark = (anchor: DocumentKnowledgeAnchor): Omit<DocumentMark, "passageKey"> => ({
    anchor, authorKind: "user", authorId: options.user?.id ?? null, authorName: options.user?.name ?? null,
  })
  for (const anchor of options.drafts ?? []) add(userMark(anchor))
  if (options.manual && active && !options.drafts?.length) add(userMark(active))
  for (const row of references) {
    const author = row.marked_by
    if (row.source_id !== sourceId || row.stale || !row.anchor || !author?.name) continue
    if (author.kind !== "user" && author.kind !== "expert") continue
    add({ anchor: row.anchor, authorKind: author.kind, authorId: author.id, authorName: author.name })
  }
  if (!options.manual && !options.cleared && active) {
    add({ anchor: active, authorKind: "passage", authorId: null, authorName: null })
  }
  return marks
}

export type TextSegment = { text: string; mark: DocumentMark | null }

export function textMarkSegments(text: string, marks: DocumentMark[]): TextSegment[] {
  const ranges: { start: number; end: number; mark: DocumentMark }[] = []
  for (const mark of marks) {
    const exact = mark.anchor.exact_text ?? ""
    if (!exact) continue
    const start = textOccurrenceIndex(text, exact, mark.anchor.prefix_text)
    if (start < 0) continue
    ranges.push({ start, end: start + exact.length, mark })
  }
  ranges.sort((left, right) => left.start - right.start || right.end - left.end)
  const segments: TextSegment[] = []
  let at = 0
  for (const range of ranges) {
    if (range.start < at) continue
    if (range.start > at) segments.push({ text: text.slice(at, range.start), mark: null })
    segments.push({ text: text.slice(range.start, range.end), mark: range.mark })
    at = range.end
  }
  if (at < text.length) segments.push({ text: text.slice(at), mark: null })
  return segments.length ? segments : [{ text, mark: null }]
}

export function workspaceFocusReference(workspace: Pick<Workspace, "references" | "sources">, referenceId: unknown): SourceReference {
  const reference = workspace.references.find((row) => row.reference_id === referenceId)
  if (!reference) throw new Error("document_anchor_position_required")
  const anchor = reference.anchor
  if (!anchor || (anchor.locator === "document" && anchor.page_number == null)
    || (!anchor.exact_text?.trim() && !anchor.rects.length)) throw new Error("document_anchor_position_required")
  const source = workspace.sources.find((row) => row.id === reference.source_id)
  if (source?.content_type === "application/pdf" && pdfAnchorKind(anchor) !== "page") throw new Error("document_anchor_position_required")
  return reference
}
