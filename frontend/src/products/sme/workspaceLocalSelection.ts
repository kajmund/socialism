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

export function localSelectionMatchesReference(local: LocalDocumentSelection, reference: SourceReference): boolean {
  const anchor = local.selection?.anchor, verified = reference.anchor
  if (!anchor || !verified || local.sourceId !== reference.source_id || local.selection?.source_version !== reference.source_version) return false
  return anchor.anchor_type === verified.anchor_type && anchor.page_number === verified.page_number && anchor.locator === verified.locator
    && (anchor.exact_text ?? "").replace(/\s/g, "").toLowerCase() === (verified.exact_text ?? "").replace(/\s/g, "").toLowerCase()
    && JSON.stringify(anchor.rects.map(({ x, y, width, height }) => [x, y, width, height])) === JSON.stringify(verified.rects.map(({ x, y, width, height }) => [x, y, width, height]))
}

export function withLocalDocumentSelection(state: WorkspaceState, local: LocalDocumentSelection | null): WorkspaceState {
  if (!local) return state
  return {
    ...state,
    selection: local.selection,
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
