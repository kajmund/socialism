import type { Workspace } from "./voiceWorkspaces"

export function requireVoiceWorkspace(value: unknown): Workspace {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("voice_workspace_response_invalid")
  const row = value as Record<string, unknown>
  const state = row.state
  if (typeof row.id !== "string" || typeof row.workspace_id !== "string" || typeof row.chat_id !== "string"
    || typeof row.customer_id !== "number" || typeof row.revision !== "number"
    || typeof row.title !== "string" || typeof row.module !== "string"
    || !state || typeof state !== "object" || Array.isArray(state)
    || ![row.sources, row.artifacts, row.references, row.research].every(Array.isArray)) throw new Error("voice_workspace_response_invalid")
  const snapshot = state as Record<string, unknown>
  if (!["sv", "en", "nb"].includes(String(snapshot.language))
    || !["workspace", "general", "research"].includes(String(snapshot.knowledge_scope))
    || !["evidence", "comparison", "documents", "relations"].includes(String(snapshot.view))
    || ![snapshot.documents, snapshot.split_source_ids, snapshot.research_attempt_ids].every(Array.isArray)) throw new Error("voice_workspace_response_invalid")
  return value as Workspace
}
