export type ModelTraceKind = "context" | "message" | "tools" | "tool_call" | "tool_result"

export type ModelTraceEntry = {
  id: string
  kind: ModelTraceKind
  text: string
  name: string
  arguments: Record<string, unknown> | null
  model: string
  role: string
}

export function acceptModelTraceWorkspace(
  eventWorkspaceId: string,
  currentWorkspaceId: string | null | undefined,
): boolean {
  return !eventWorkspaceId || eventWorkspaceId === currentWorkspaceId
}

const TRACE_KINDS: readonly ModelTraceKind[] = ["context", "message", "tools", "tool_call", "tool_result"]

function traceKind(value: unknown): ModelTraceKind | null {
  return TRACE_KINDS.find((kind) => kind === value) ?? null
}

export function modelTraceEntry(raw: Record<string, unknown>): ModelTraceEntry | null {
  const kind = traceKind(raw.kind)
  if (kind === null) return null
  const text = typeof raw.text === "string" ? raw.text : ""
  const name = typeof raw.name === "string" ? raw.name : ""
  const model = typeof raw.model === "string" ? raw.model : ""
  const role = typeof raw.role === "string" ? raw.role : ""
  const args = raw.arguments
  const argumentsValue = args && typeof args === "object" && !Array.isArray(args)
    ? args as Record<string, unknown>
    : null
  const textual = kind === "context" || kind === "message" || kind === "tools"
  if (textual && !text.trim()) return null
  if (!textual && !name) return null
  const traceId = typeof raw.trace_id === "string" ? raw.trace_id : ""
  const callId = typeof raw.call_id === "string" ? raw.call_id : ""
  return {
    id: traceId || (callId ? `${kind}:${callId}` : `${kind}:${text}`),
    kind,
    text,
    name,
    arguments: argumentsValue,
    model,
    role,
  }
}

export function appendModelTrace(
  rows: ModelTraceEntry[],
  entry: ModelTraceEntry,
): ModelTraceEntry[] {
  if (rows.some((row) => row.id === entry.id)) return rows
  return [...rows, entry].slice(-200)
}
