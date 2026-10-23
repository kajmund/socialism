import type { DecisionAnswer } from "@/api/clauseSsr"

export type QueueKeyAction = DecisionAnswer | "undo" | "prev"

export function keyToQueueAction(key: string): QueueKeyAction | null {
  switch (key.toLowerCase()) {
    case "j":
      return "yes"
    case "n":
      return "no"
    case "s":
    case "arrowright":
      return "skip"
    case "u":
      return "unsure"
    case "z":
    case "backspace":
      return "undo"
    case "p":
    case "arrowleft":
      return "prev"
    default:
      return null
  }
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (target == null || typeof target !== "object") return false
  const el = target as { tagName?: string; isContentEditable?: boolean }
  const tag = el.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || Boolean(el.isContentEditable)
}
