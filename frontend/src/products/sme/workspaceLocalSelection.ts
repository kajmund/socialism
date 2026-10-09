import type { SourceReference, WorkspaceSelection, WorkspaceState } from "@/api/voiceWorkspaces"
import type { WorkspaceTurnSnapshot } from "./workspaceTurnSnapshot"
import { clearWorkspaceDocumentSelection } from "./workspaceDocumentFocus"

export type LocalDocumentSelection = { sourceId: string; selection: WorkspaceSelection | null; clearedSourceIds?: string[] }

export function clearLocalDocumentSelection(state: WorkspaceState, references: SourceReference[], local: LocalDocumentSelection | null, sourceId: string): LocalDocumentSelection {
  const visible = withLocalDocumentSelection(state, local)
  const cleared = clearWorkspaceDocumentSelection(visible, sourceId, references)
  const clearedSourceIds = [...new Set([...(local?.clearedSourceIds ?? []), sourceId])]
  if (local && cleared.selection === visible.selection) return { ...local, clearedSourceIds }
  return { sourceId, selection: cleared.selection ?? null, clearedSourceIds }
}

function normalizedQuote(text: string | null | undefined): string {
  return (text ?? "").replace(/\s/g, "").toLowerCase()
}

function anchorGeometryEqual(
  left: NonNullable<WorkspaceSelection["anchor"]>,
  right: NonNullable<WorkspaceSelection["anchor"]>,
): boolean {
  return left.anchor_type === right.anchor_type && left.page_number === right.page_number && left.locator === right.locator
    && normalizedQuote(left.exact_text) === normalizedQuote(right.exact_text)
    && JSON.stringify(left.rects.map(({ x, y, width, height }) => [x, y, width, height]))
      === JSON.stringify(right.rects.map(({ x, y, width, height }) => [x, y, width, height]))
}

export function selectionsSameGeometry(local: WorkspaceSelection, server: WorkspaceSelection): boolean {
  if (!local.source_id || !server.source_id || local.source_id !== server.source_id) return false
  const left = local.anchor
  const right = server.anchor
  if (left == null || right == null) return false
  return anchorGeometryEqual(left, right)
}

export function mergeMaterializedSelection(local: WorkspaceSelection, server: WorkspaceSelection | null | undefined): WorkspaceSelection {
  if (!server?.reference_id || local.reference_id || !selectionsSameGeometry(local, server)) return local
  return {
    ...local,
    reference_id: server.reference_id,
    source_version: server.source_version ?? local.source_version,
    source_file_sha256: server.source_file_sha256 ?? local.source_file_sha256,
  }
}

export function localSelectionMatchesReference(local: LocalDocumentSelection, reference: SourceReference): boolean {
  const anchor = local.selection?.anchor, verified = reference.anchor
  if (!anchor || !verified || local.sourceId !== reference.source_id || local.selection?.source_version !== reference.source_version) return false
  return anchorGeometryEqual(anchor, verified)
}

export function withLocalDocumentSelection(state: WorkspaceState, local: LocalDocumentSelection | null): WorkspaceState {
  if (!local) return state
  const selection = local.selection
    ? mergeMaterializedSelection(local.selection, state.selection)
    : null
  return {
    ...state,
    selection,
    documents: state.documents.map((row) => row.source_id === local.sourceId || local.clearedSourceIds?.includes(row.source_id) ? { ...row, reference_id: null } : row),
  }
}

export function captureDocumentTurn(commit: Promise<WorkspaceTurnSnapshot | null>, local: LocalDocumentSelection | null): Promise<WorkspaceTurnSnapshot | null> {
  // Copy the local intent before awaiting navigation or session startup.
  const selected = structuredClone(local)
  const captured = commit.then((value) => value ? {
    workspaceId: value.workspaceId,
    revision: value.revision,
    state: withLocalDocumentSelection(structuredClone(value.state), selected),
  } : null)
  void captured.catch(() => undefined)
  return captured
}
