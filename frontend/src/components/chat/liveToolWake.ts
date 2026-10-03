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
