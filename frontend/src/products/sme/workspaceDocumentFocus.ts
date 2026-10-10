import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { SourceReference, Workspace, WorkspaceState } from "@/api/voiceWorkspaces"
import { pdfAnchorKind, pdfAnchorRectangles } from "@/components/underlag/pdfAnchorPresentation"

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

export function visibleDocumentHighlights(
  references: Pick<SourceReference, "source_id" | "stale" | "anchor">[],
  sourceId: string,
  page: number,
  active: DocumentKnowledgeAnchor | null | undefined,
): DocumentKnowledgeAnchor[] {
  if (active === null) return []
  const seen = new Set<string>()
  const anchors: DocumentKnowledgeAnchor[] = []
  const add = (anchor: DocumentKnowledgeAnchor | null | undefined) => {
    if (!anchor || anchor.page_number !== page || !pdfAnchorRectangles(anchor).length) return
    const key = JSON.stringify(anchor.rects.map(({ x, y, width, height }) => [x, y, width, height]))
    if (seen.has(key)) return
    seen.add(key)
    anchors.push(anchor)
  }
  add(active)
  for (const row of references) if (row.source_id === sourceId && !row.stale) add(row.anchor)
  return anchors
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
