type UnknownRecord = Record<string, unknown>

export type OpenAIRealtimeToolCall = {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export type OpenAIRealtimeServerEvent = {
  sessionReady: boolean
  interrupted: boolean
  audioChunks: string[]
  inputFormat: string | null
  outputFormat: string | null
  ping: { eventId: number; pingMs: number | null } | null
  toolCalls: OpenAIRealtimeToolCall[]
  cancelledToolCallIds: string[]
  userTranscript: string
  assistantTranscript: string
  turnComplete: boolean
}

export type OpenAIRealtimeTranscriptState = {
  input: string
  output: string
}

function asRecord(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null
    ? (value as UnknownRecord)
    : null
}

function emptyEvent(): OpenAIRealtimeServerEvent {
  return {
    sessionReady: false,
    interrupted: false,
    audioChunks: [],
    inputFormat: null,
    outputFormat: null,
    ping: null,
    toolCalls: [],
    cancelledToolCallIds: [],
    userTranscript: "",
    assistantTranscript: "",
    turnComplete: false,
  }
}

function toolArguments(value: unknown): Record<string, unknown> {
  if (typeof value !== "string" || !value.trim()) return {}
  try {
    return asRecord(JSON.parse(value)) ?? {}
  } catch {
    return {}
  }
}

/** Collects input_text parts from a user message item, e.g. the greeting echo. */
function userItemText(item: UnknownRecord): string {
  if (item.type !== "message" || item.role !== "user") return ""
  if (!Array.isArray(item.content)) return ""
  return item.content
    .map((part) => {
      const record = asRecord(part)
      return record?.type === "input_text" && typeof record.text === "string"
        ? record.text
        : ""
    })
    .join("")
}

export function parseOpenAIRealtimeMessage(
  raw: string,
): OpenAIRealtimeServerEvent {
  const message = asRecord(JSON.parse(raw))
  if (!message) return emptyEvent()
  switch (message.type) {
    case "session.created":
    case "session.updated":
      return { ...emptyEvent(), sessionReady: true }
    case "input_audio_buffer.speech_started":
      return { ...emptyEvent(), interrupted: true }
    case "response.output_audio.delta": {
      const delta =
        typeof message.delta === "string" && message.delta ? [message.delta] : []
      return { ...emptyEvent(), audioChunks: delta }
    }
    case "response.output_audio_transcript.delta": {
      const delta = typeof message.delta === "string" ? message.delta : ""
      return { ...emptyEvent(), assistantTranscript: delta }
    }
    case "response.function_call_arguments.done": {
      if (
        typeof message.call_id !== "string" ||
        typeof message.name !== "string"
      ) {
        return emptyEvent()
      }
      return {
        ...emptyEvent(),
        toolCalls: [
          {
            id: message.call_id,
            name: message.name,
            arguments: toolArguments(message.arguments),
          },
        ],
      }
    }
    case "conversation.item.input_audio_transcription.completed": {
      const transcript =
        typeof message.transcript === "string" ? message.transcript : ""
      return { ...emptyEvent(), userTranscript: transcript }
    }
    case "conversation.item.added":
    case "conversation.item.created": {
      const item = asRecord(message.item)
      if (!item) return emptyEvent()
      const text = userItemText(item)
      return text ? { ...emptyEvent(), userTranscript: text } : emptyEvent()
    }
    case "response.done":
      return { ...emptyEvent(), turnComplete: true }
    default:
      return emptyEvent()
  }
}

export function updateOpenAIRealtimeTranscripts(
  state: OpenAIRealtimeTranscriptState,
  event: OpenAIRealtimeServerEvent,
): {
  state: OpenAIRealtimeTranscriptState
  completed: OpenAIRealtimeTranscriptState | null
  orphanOutput: string | null
} {
  const startsNewUserTurn = Boolean(event.userTranscript && state.output)
  const next = {
    input: (startsNewUserTurn ? "" : state.input) + event.userTranscript,
    output:
      (event.interrupted || startsNewUserTurn ? "" : state.output) +
      event.assistantTranscript,
  }
  if (!event.turnComplete) return { state: next, completed: null, orphanOutput: null }
  const completed = {
    input: next.input.trim(),
    output: next.output.trim(),
  }
  return {
    state: { input: "", output: "" },
    completed: completed.input && completed.output ? completed : null,
    orphanOutput: completed.input || !completed.output ? null : completed.output,
  }
}

function userTextTurnMessages(text: string): string[] {
  return [
    JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text }],
      },
    }),
    JSON.stringify({ type: "response.create" }),
  ]
}

export function openaiRealtimeGreetingMessages(initialTurn: string): string[] {
  return userTextTurnMessages(initialTurn)
}

export function openaiRealtimeWakeMessages(result: string): string[] {
  return userTextTurnMessages(result)
}

export function openaiRealtimeAudioMessage(pcmBase64: string): string {
  return JSON.stringify({ type: "input_audio_buffer.append", audio: pcmBase64 })
}

export function openaiRealtimeToolResultMessage(
  responses: Array<{ id: string; name: string; result: string; isError?: boolean }>,
): string[] {
  return responses.map((response) =>
    JSON.stringify({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: response.id,
        output: response.result,
      },
    }),
  )
}

export function openaiRealtimeCloseMessage(): string | null {
  return null
}

export function openaiRealtimePongMessage(): string | null {
  return null
}
