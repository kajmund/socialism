import type { WatchEvent, WordAction } from "@/lib/types"

export type WatchAction =
  | { kind: "upsert"; actions: WordAction[] }
  | { kind: "finished"; status: string; error?: string }

export function actionsForWatchEvent(event: WatchEvent): WatchAction[] {
  switch (event.type) {
    case "expertgranskning.replay":
      return [{ kind: "upsert", actions: event.actions }]
    case "expertgranskning.action.created":
    case "expertgranskning.action.updated":
      return [{ kind: "upsert", actions: [event.action] }]
    case "expertgranskning.finished":
      return [{ kind: "finished", status: event.status, error: event.error }]
    default: {
      const _exhaustive: never = event
      return _exhaustive
    }
  }
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
