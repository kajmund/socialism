import type { SourceReference, Workspace } from "@/api/voiceWorkspaces"
import { pdfAnchorKind } from "@/components/underlag/pdfAnchorPresentation"

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
