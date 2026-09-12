import type { WatchEvent, WordAction } from "@/lib/types"

export function canAutoApply(action: WordAction): boolean {
  return action.status === "pending"
}

export function shouldAutoApplyAction(
  insertedIds: ReadonlySet<string>,
  action: WordAction,
): boolean {
  if (!canAutoApply(action)) return false
  if (insertedIds.has(action.id)) return false
  if (action.word_artifact_id) return false
  return action.content.trim().length > 0
}

export type WatchAction =
  | { kind: "insert"; actions: WordAction[] }
  | { kind: "remember"; ids: string[] }
  | { kind: "finished"; status: string; error?: string }

export function actionsForWatchEvent(
  event: WatchEvent,
  insertedIds: ReadonlySet<string>,
): WatchAction[] {
  switch (event.type) {
    case "expertgranskning.replay":
      return actionsForWordActions(event.actions, insertedIds)
    case "expertgranskning.action.created":
      return actionsForWordActions([event.action], insertedIds)
    case "expertgranskning.action.updated":
      return [{ kind: "remember", ids: [event.action.id] }]
    case "expertgranskning.finished":
      return [{ kind: "finished", status: event.status, error: event.error }]
    default: {
      const _exhaustive: never = event
      return _exhaustive
    }
  }
}

function actionsForWordActions(
  actions: WordAction[],
  insertedIds: ReadonlySet<string>,
): WatchAction[] {
  const remember = actions
    .filter(
      (row) =>
        !canAutoApply(row) || row.word_artifact_id || insertedIds.has(row.id),
    )
    .map((row) => row.id)
  const insert = actions.filter((row) => shouldAutoApplyAction(insertedIds, row))
  const planned: WatchAction[] = []
  if (remember.length > 0) planned.push({ kind: "remember", ids: remember })
  if (insert.length > 0) planned.push({ kind: "insert", actions: insert })
  return planned
}

export function isWatchEvent(value: unknown): value is WatchEvent {
  if (value == null || typeof value !== "object") return false
  const type = (value as { type?: unknown }).type
  return (
    type === "expertgranskning.replay" ||
    type === "expertgranskning.action.created" ||
    type === "expertgranskning.action.updated" ||
    type === "expertgranskning.finished"
  )
}
