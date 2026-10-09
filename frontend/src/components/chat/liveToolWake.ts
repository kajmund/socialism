export const VOICE_TOOL_WAKE_PREFIX = "[[underlag]]"

export function deferredToolResult(): string {
  return JSON.stringify({
    status: "deferred",
    instruction: "Säg inget mer i den här turen.",
  })
}

export function voiceToolWakeText(result: string): string {
  return `${VOICE_TOOL_WAKE_PREFIX}\n${result}`
}

export function isVoiceToolWake(userMessage: string): boolean {
  return userMessage.trim().startsWith(VOICE_TOOL_WAKE_PREFIX)
}

const TOOL_CALL_KEYS = new Set(["tool", "name", "arguments", "parameters"])

/** Drop a model-written [[underlag]] tool payload so the chat shows the sentence only. */
export function stripWakeToolText(text: string): string {
  const needle = VOICE_TOOL_WAKE_PREFIX.toLowerCase()
  const lowered = text.toLowerCase()
  let result = ""
  let start = 0
  while (start < text.length) {
    const at = lowered.indexOf(needle, start)
    if (at < 0) return (result + text.slice(start)).trim()
    let cursor = at + VOICE_TOOL_WAKE_PREFIX.length
    while (cursor < text.length && /\s/.test(text[cursor])) cursor += 1
    const end = text[cursor] === "{" ? jsonObjectEnd(text, cursor) : null
    const parsed = end === null ? null : toolObject(text.slice(cursor, end))
    if (end === null || parsed === null) {
      result += text.slice(start, at + VOICE_TOOL_WAKE_PREFIX.length)
      start = at + VOICE_TOOL_WAKE_PREFIX.length
      continue
    }
    result += text.slice(start, at)
    start = end
  }
  return result.trim()
}

function toolObject(raw: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null
    const record = parsed as Record<string, unknown>
    if (!Object.keys(record).every((key) => TOOL_CALL_KEYS.has(key))) return null
    const name = record.tool ?? record.name
    const args = "arguments" in record ? record.arguments : record.parameters
    if (typeof name !== "string" || !name.trim()) return null
    if (!args || typeof args !== "object" || Array.isArray(args)) return null
    if (!Object.values(args as Record<string, unknown>).some((value) => String(value).trim())) return null
    return record
  } catch {
    return null
  }
}

function jsonObjectEnd(text: string, open: number): number | null {
  let depth = 0
  let inString = false
  let escape = false
  for (let index = open; index < text.length; index += 1) {
    const char = text[index]
    if (inString) {
      if (escape) escape = false
      else if (char === "\\") escape = true
      else if (char === '"') inString = false
      continue
    }
    if (char === '"') inString = true
    else if (char === "{") depth += 1
    else if (char === "}") {
      depth -= 1
      if (depth === 0) return index + 1
    }
  }
  return null
}

/** True when the tool result must not be spoken in the turn that asked for it. */
export function shouldDeferLiveTool(
  snapshot: string,
  currentInput: string,
  interruptedDuringTool: boolean,
): boolean {
  if (interruptedDuringTool) return true
  const current = currentInput.trim()
  if (!current || current === snapshot) return false
  return !(
    snapshot &&
    (current.startsWith(snapshot) || snapshot.startsWith(current))
  )
}
