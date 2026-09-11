import type { ReviewResult, WatchEvent } from "@/lib/types"

export function canAutoApply(result: ReviewResult): boolean {
  return result.status === "pending"
}

export function shouldInsertComment(
  insertedIds: ReadonlySet<string>,
  result: ReviewResult,
): boolean {
  if (!canAutoApply(result)) return false
  if (insertedIds.has(result.id)) return false
  if (result.comment_id) return false
  if (result.is_rewrite_suggestion) {
    return Boolean(result.foreslagen_text?.trim())
  }
  return result.kommentar.trim().length > 0
}

export function formatCommentBody(result: ReviewResult): string {
  const text = result.kommentar.trim()
  if (result.is_heading_suggestion || !result.expert_namn.trim()) {
    return text
  }
  return `${result.expert_namn.trim()}: ${text}`
}

export type WatchAction =
  | { kind: "insert"; results: ReviewResult[] }
  | { kind: "remember"; ids: string[] }
  | { kind: "finished"; status: string; error?: string }

export function actionsForWatchEvent(
  event: WatchEvent,
  insertedIds: ReadonlySet<string>,
): WatchAction[] {
  switch (event.type) {
    case "expertgranskning.replay":
      return actionsForResults(event.results, insertedIds)
    case "expertgranskning.result.created":
      return actionsForResults([event.result], insertedIds)
    case "expertgranskning.result.updated":
      return [{ kind: "remember", ids: [event.result.id] }]
    case "expertgranskning.finished":
      return [{ kind: "finished", status: event.status, error: event.error }]
    default: {
      const _exhaustive: never = event
      return _exhaustive
    }
  }
}

function actionsForResults(
  results: ReviewResult[],
  insertedIds: ReadonlySet<string>,
): WatchAction[] {
  const remember = results
    .filter((row) => !canAutoApply(row) || row.comment_id || insertedIds.has(row.id))
    .map((row) => row.id)
  const insert = results.filter((row) => shouldInsertComment(insertedIds, row))
  const actions: WatchAction[] = []
  if (remember.length > 0) actions.push({ kind: "remember", ids: remember })
  if (insert.length > 0) actions.push({ kind: "insert", results: insert })
  return actions
}

export function isWatchEvent(value: unknown): value is WatchEvent {
  if (value == null || typeof value !== "object") return false
  const type = (value as { type?: unknown }).type
  return (
    type === "expertgranskning.replay" ||
    type === "expertgranskning.result.created" ||
    type === "expertgranskning.result.updated" ||
    type === "expertgranskning.finished"
  )
}
