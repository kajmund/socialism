import type { Workspace, WorkspaceState } from "@/api/voiceWorkspaces"

export type WorkspaceTurnSnapshot = { workspaceId: string; revision: number; state: WorkspaceState }
type WorkspaceTurnCommit = WorkspaceTurnSnapshot | Pick<Workspace, "id" | "revision" | "state">

export function captureWorkspaceTurn(commit: WorkspaceTurnCommit | Promise<WorkspaceTurnCommit>): Promise<WorkspaceTurnSnapshot> {
  // Bind a turn to this commit, even if another selection is queued while it saves.
  const snapshot = Promise.resolve(commit).then((value) => ({ workspaceId: "id" in value ? value.id : value.workspaceId, revision: value.revision, state: structuredClone(value.state) }))
  // A failed save may have no waiting turn. Keep its rejection for any later caller.
  void snapshot.catch(() => undefined)
  return snapshot
}
