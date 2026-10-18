import type { DocumentKnowledgeAnchor } from "@/api/underlag"
import type { SourceReference, WorkspaceSelection, WorkspaceState } from "@/api/voiceWorkspaces"
import type { WorkspaceTurnSnapshot } from "./workspaceTurnSnapshot"
import { clearWorkspaceDocumentSelection } from "./workspaceDocumentFocus"
import { passageCommentKey } from "./passageCommentKey"

export type LocalDocumentSelection = {
  sourceId: string
  selection: WorkspaceSelection | null
  earlierBySource?: Record<string, WorkspaceSelection[]>
  clearedSourceIds?: string[]
}

function keptMarks(marks: Record<string, WorkspaceSelection[]>): Record<string, WorkspaceSelection[]> | undefined {
  return Object.keys(marks).length ? marks : undefined
}

export function addLocalDocumentSelection(local: LocalDocumentSelection | null, sourceId: string, selection: WorkspaceSelection): LocalDocumentSelection {
  const earlierBySource = { ...(local?.earlierBySource ?? {}) }
  const previous = local?.selection
  if (previous?.anchor && local?.sourceId && !(local.sourceId === sourceId && selectionsSameGeometry(previous, selection))) {
    const bucket = earlierBySource[local.sourceId] ?? []
    if (!bucket.some((row) => selectionsSameGeometry(row, previous))) earlierBySource[local.sourceId] = [...bucket, structuredClone(previous)]
  }
  earlierBySource[sourceId] = (earlierBySource[sourceId] ?? []).filter((row) => !selectionsSameGeometry(row, selection))
  if (!earlierBySource[sourceId]?.length) delete earlierBySource[sourceId]
  return {
    sourceId,
    selection: structuredClone(selection),
    earlierBySource: keptMarks(earlierBySource),
    clearedSourceIds: (local?.clearedSourceIds ?? []).filter((id) => id !== sourceId),
  }
}

export function localUserAnchors(local: LocalDocumentSelection | null, sourceId: string): DocumentKnowledgeAnchor[] | null {
  if (!local) return null
  if (local.clearedSourceIds?.includes(sourceId)) return []
  const earlier = (local.earlierBySource?.[sourceId] ?? []).flatMap((row) => row.anchor ? [row.anchor] : [])
  const active = local.sourceId === sourceId && local.selection?.anchor ? [local.selection.anchor] : []
  if (!earlier.length && !active.length) return null
  return [...earlier, ...active]
}

export function dropLocalPassage(local: LocalDocumentSelection | null, sourceId: string, passageKey: string): LocalDocumentSelection | null {
  if (!local) return null
  const matches = (row: WorkspaceSelection | null | undefined) => Boolean(
    row?.anchor && row.source_id === sourceId && passageCommentKey(sourceId, row.anchor) === passageKey,
  )
  const earlierBySource = { ...(local.earlierBySource ?? {}) }
  const bucket = earlierBySource[sourceId]
  if (bucket) {
    const kept = bucket.filter((row) => !matches(row))
    if (kept.length) earlierBySource[sourceId] = kept
    else delete earlierBySource[sourceId]
  }
  return {
    ...local,
    selection: matches(local.selection) ? null : local.selection,
    earlierBySource: keptMarks(earlierBySource),
  }
}

export function clearLocalDocumentSelection(state: WorkspaceState, references: SourceReference[], local: LocalDocumentSelection | null, sourceId: string): LocalDocumentSelection {
  const visible = withLocalDocumentSelection(state, local)
  const cleared = clearWorkspaceDocumentSelection(visible, sourceId, references)
  const clearedSourceIds = [...new Set([...(local?.clearedSourceIds ?? []), sourceId])]
  const earlierBySource = { ...(local?.earlierBySource ?? {}) }
  delete earlierBySource[sourceId]
  const kept = keptMarks(earlierBySource)
  if (local && cleared.selection === visible.selection) return { ...local, clearedSourceIds, earlierBySource: kept }
  return { sourceId, selection: cleared.selection ?? null, clearedSourceIds, earlierBySource: kept }
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
