type UnknownRecord = Record<string, unknown>

export type ElevenLabsToolCall = {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export type ElevenLabsServerEvent = {
  sessionReady: boolean
  interrupted: boolean
  audioChunks: string[]
  inputFormat: string | null
  outputFormat: string | null
  ping: { eventId: number; pingMs: number | null } | null
  toolCalls: ElevenLabsToolCall[]
  userTranscript: string
  assistantTranscript: string
}

export type ElevenLabsTranscriptState = {
  input: string
  output: string
}

function asRecord(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null
    ? (value as UnknownRecord)
    : null
}

function emptyEvent(): ElevenLabsServerEvent {
  return {
    sessionReady: false,
    interrupted: false,
    audioChunks: [],
    inputFormat: null,
    outputFormat: null,
    ping: null,
    toolCalls: [],
    userTranscript: "",
    assistantTranscript: "",
  }
}

function asFormat(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

function toolArguments(value: unknown): Record<string, unknown> {
  const record = asRecord(value)
  if (record) return record
  if (typeof value === "string" && value.trim()) {
    try {
      const parsed = asRecord(JSON.parse(value))
      if (parsed) return parsed
    } catch {
      return {}
    }
  }
  return {}
}

export function parseElevenLabsMessage(raw: string): ElevenLabsServerEvent {
  const message = asRecord(JSON.parse(raw))
  if (!message) return emptyEvent()
  const type = message.type
  if (type === "ping") {
    const pingEvent = asRecord(message.ping_event)
    if (pingEvent && typeof pingEvent.event_id === "number") {
      return {
        ...emptyEvent(),
        ping: {
          eventId: pingEvent.event_id,
          pingMs: typeof pingEvent.ping_ms === "number" ? pingEvent.ping_ms : null,
        },
      }
    }
    return emptyEvent()
  }
  if (type === "conversation_initiation_metadata") {
    const meta = asRecord(message.conversation_initiation_metadata_event)
    return {
      ...emptyEvent(),
      sessionReady: true,
      inputFormat: asFormat(meta?.user_input_audio_format),
      outputFormat: asFormat(meta?.agent_output_audio_format),
    }
  }
  if (type === "audio") {
    const audioEvent = asRecord(message.audio_event)
    const chunk = audioEvent?.audio_base_64
    return {
      ...emptyEvent(),
      audioChunks: typeof chunk === "string" && chunk ? [chunk] : [],
    }
  }
  if (type === "user_transcript") {
    const event = asRecord(message.user_transcription_event)
    const text = event?.user_transcript
    return {
      ...emptyEvent(),
      userTranscript: typeof text === "string" ? text : "",
    }
  }
  if (type === "agent_response") {
    const event = asRecord(message.agent_response_event)
    const text = event?.agent_response
    return {
      ...emptyEvent(),
      assistantTranscript: typeof text === "string" ? text : "",
    }
  }
  if (type === "agent_response_correction") {
    const event = asRecord(message.agent_response_correction_event)
    const text = event?.corrected_agent_response
    return {
      ...emptyEvent(),
      assistantTranscript: typeof text === "string" ? text : "",
    }
  }
  if (type === "interruption") {
    return { ...emptyEvent(), interrupted: true }
  }
  if (type === "client_tool_call") {
    const call = asRecord(message.client_tool_call)
    if (
      call &&
      typeof call.tool_call_id === "string" &&
      typeof call.tool_name === "string"
    ) {
      return {
        ...emptyEvent(),
        toolCalls: [
          {
            id: call.tool_call_id,
            name: call.tool_name,
            arguments: toolArguments(call.parameters),
          },
        ],
      }
    }
    return emptyEvent()
  }
  return emptyEvent()
}

export function updateElevenLabsTranscripts(
  state: ElevenLabsTranscriptState,
  event: ElevenLabsServerEvent,
): {
  state: ElevenLabsTranscriptState
  completed: ElevenLabsTranscriptState | null
} {
  const next = {
    input: event.userTranscript ? event.userTranscript : state.input,
    output: event.interrupted
      ? ""
      : event.assistantTranscript
        ? event.assistantTranscript
        : state.output,
  }
  if (event.interrupted) {
    return { state: next, completed: null }
  }
  if (!event.assistantTranscript) {
    return { state: next, completed: null }
  }
  const completed = {
    input: next.input.trim(),
    output: next.output.trim(),
  }
  if (!completed.input || !completed.output) {
    return { state: next, completed: null }
  }
  return {
    state: { input: "", output: "" },
    completed,
  }
}

export function elevenLabsUserAudioMessage(data: string): string {
  return JSON.stringify({ user_audio_chunk: data })
}

export function elevenLabsPongMessage(eventId: number): string {
  return JSON.stringify({ type: "pong", event_id: eventId })
}

export function elevenLabsToolResultMessage(
  responses: Array<{ id: string; name?: string; result: string; isError?: boolean }>,
): string[] {
  return responses.map((response) =>
    JSON.stringify({
      type: "client_tool_result",
      tool_call_id: response.id,
      result: response.result,
      is_error: response.isError === true,
    }),
  )
}

export function elevenLabsInitiationMessage(
  clientInit: Record<string, unknown>,
): string {
  return JSON.stringify(clientInit)
}
