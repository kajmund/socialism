import type { WorkspaceState } from "@/api/voiceWorkspaces"

export type WorkspaceTurnSnapshot = { revision: number; state: WorkspaceState }

export function captureWorkspaceTurn(commit: WorkspaceTurnSnapshot | Promise<WorkspaceTurnSnapshot>): Promise<WorkspaceTurnSnapshot> {
  // Bind a turn to this commit, even if another selection is queued while it saves.
  const snapshot = Promise.resolve(commit).then(({ revision, state }) => ({ revision, state: structuredClone(state) }))
  // A failed save may have no waiting turn. Keep its rejection for any later caller.
  void snapshot.catch(() => undefined)
  return snapshot
}
