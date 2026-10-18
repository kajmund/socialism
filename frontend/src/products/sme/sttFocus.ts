/** Source ids of the documents on screen, from a workspace-state context line. */
export function sourceIdsFromWorkspaceContext(text: string): string[] | null {
  const marker = "Workspace state updated: "
  if (!text.startsWith(marker)) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(text.slice(marker.length))
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== "object") return null
  const state = parsed as { documents?: unknown; split_source_ids?: unknown; active_source_id?: unknown }
  const split = strings(state.split_source_ids)
  if (split.length === 2) return split
  const documents = sourceIds(state.documents)
  if (typeof state.active_source_id === "string" && documents.includes(state.active_source_id)) {
    return [state.active_source_id]
  }
  return documents.length > 0 ? documents.slice(0, 1) : []
}

function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === "string" && item.length > 0).slice(0, 2)
}

function sourceIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const ids: string[] = []
  for (const item of value) {
    if (!item || typeof item !== "object") continue
    const sourceId = (item as { source_id?: unknown }).source_id
    if (typeof sourceId === "string" && sourceId) ids.push(sourceId)
  }
  return ids
}
