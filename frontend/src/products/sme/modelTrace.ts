export type ModelTraceKind = "message" | "tool_call" | "tool_result"

export type ModelTraceEntry = {
  id: string
  kind: ModelTraceKind
  text: string
  name: string
  arguments: Record<string, unknown> | null
}

export function acceptModelTraceWorkspace(
  eventWorkspaceId: string,
  currentWorkspaceId: string | null | undefined,
): boolean {
  return !eventWorkspaceId || eventWorkspaceId === currentWorkspaceId
}

export function modelTraceEntry(raw: Record<string, unknown>): ModelTraceEntry | null {
  const kind = raw.kind
  if (kind !== "message" && kind !== "tool_call" && kind !== "tool_result") return null
  const text = typeof raw.text === "string" ? raw.text : ""
  const name = typeof raw.name === "string" ? raw.name : ""
  const args = raw.arguments
  const argumentsValue = args && typeof args === "object" && !Array.isArray(args)
    ? args as Record<string, unknown>
    : null
  if (kind === "message" && !text.trim()) return null
  if (kind !== "message" && !name) return null
  const callId = typeof raw.call_id === "string" ? raw.call_id : ""
  return {
    id: callId ? `${kind}:${callId}` : `${kind}:${text}`,
    kind,
    text,
    name,
    arguments: argumentsValue,
  }
}

export function appendModelTrace(
  rows: ModelTraceEntry[],
  entry: ModelTraceEntry,
): ModelTraceEntry[] {
  if (rows.some((row) => row.id === entry.id)) return rows
  return [...rows, entry].slice(-200)
}
