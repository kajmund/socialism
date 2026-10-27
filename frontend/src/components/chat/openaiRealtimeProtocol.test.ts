import { describe, expect, it } from "vitest"
import {
  openaiRealtimeAudioMessage,
  openaiRealtimeCloseMessage,
  openaiRealtimeGreetingMessages,
  openaiRealtimePongMessage,
  openaiRealtimeToolResultMessage,
  openaiRealtimeWakeMessages,
  parseOpenAIRealtimeMessage,
  updateOpenAIRealtimeTranscripts,
} from "@/components/chat/openaiRealtimeProtocol"

const EMPTY_EVENT = {
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

describe("OpenAI Realtime protocol", () => {
  it("marks the session ready on session.created and session.updated", () => {
    expect(
      parseOpenAIRealtimeMessage(JSON.stringify({ type: "session.created" })),
    ).toEqual({ ...EMPTY_EVENT, sessionReady: true })
    expect(
      parseOpenAIRealtimeMessage(JSON.stringify({ type: "session.updated" })),
    ).toEqual({ ...EMPTY_EVENT, sessionReady: true })
  })

  it("extracts audio chunks from response.output_audio.delta", () => {
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({ type: "response.output_audio.delta", delta: "chunk" }),
      ).audioChunks,
    ).toEqual(["chunk"])
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({ type: "response.output_audio.delta", delta: "" }),
      ).audioChunks,
    ).toEqual([])
  })

  it("marks an interruption on input_audio_buffer.speech_started", () => {
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({ type: "input_audio_buffer.speech_started" }),
      ).interrupted,
    ).toBe(true)
  })

  it("reads user speech from input_audio_transcription.completed", () => {
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({
          type: "conversation.item.input_audio_transcription.completed",
          transcript: "Hallå",
        }),
      ).userTranscript,
    ).toBe("Hallå")
  })

  it("reads the greeting and tool-wake user text from conversation.item.added/created", () => {
    for (const type of ["conversation.item.added", "conversation.item.created"]) {
      expect(
        parseOpenAIRealtimeMessage(
          JSON.stringify({
            type,
            item: {
              type: "message",
              role: "user",
              content: [{ type: "input_text", text: "Hej, jag är Erik." }],
            },
          }),
        ).userTranscript,
      ).toBe("Hej, jag är Erik.")
    }
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({
          type: "conversation.item.added",
          item: {
            type: "message",
            role: "assistant",
            content: [{ type: "text", text: "Ignoreras" }],
          },
        }),
      ),
    ).toEqual(EMPTY_EVENT)
  })

  it("accumulates the assistant transcript from response.output_audio_transcript.delta", () => {
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({
          type: "response.output_audio_transcript.delta",
          delta: "Det tänker ",
        }),
      ).assistantTranscript,
    ).toBe("Det tänker ")
  })

  it("parses tool calls from response.function_call_arguments.done", () => {
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({
          type: "response.function_call_arguments.done",
          call_id: "call-1",
          name: "lookup_company",
          arguments: JSON.stringify({ orgnr: "556000-0000" }),
        }),
      ).toolCalls,
    ).toEqual([
      {
        id: "call-1",
        name: "lookup_company",
        arguments: { orgnr: "556000-0000" },
      },
    ])
  })

  it("tolerates malformed tool call arguments", () => {
    const event = parseOpenAIRealtimeMessage(
      JSON.stringify({
        type: "response.function_call_arguments.done",
        call_id: "call-2",
        name: "lookup_company",
        arguments: "inte json",
      }),
    )
    expect(event.toolCalls).toEqual([
      { id: "call-2", name: "lookup_company", arguments: {} },
    ])
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({
          type: "response.function_call_arguments.done",
          name: "saknar id",
          arguments: "{}",
        }),
      ).toolCalls,
    ).toEqual([])
  })

  it("marks the turn complete on response.done", () => {
    expect(
      parseOpenAIRealtimeMessage(JSON.stringify({ type: "response.done" }))
        .turnComplete,
    ).toBe(true)
  })

  it("ignores unrelated server events", () => {
    expect(
      parseOpenAIRealtimeMessage(
        JSON.stringify({ type: "response.audio.done" }),
      ),
    ).toEqual(EMPTY_EVENT)
    expect(
      parseOpenAIRealtimeMessage(JSON.stringify({ type: "error", code: "x" })),
    ).toEqual(EMPTY_EVENT)
  })

  it("pairs the user turn with the assistant reply for memory", () => {
    const afterUser = updateOpenAIRealtimeTranscripts(
      { input: "", output: "" },
      {
        ...EMPTY_EVENT,
        userTranscript: "Vad minns du?",
      },
    )
    expect(afterUser.completed).toBeNull()
    expect(afterUser.state.input).toBe("Vad minns du?")

    const afterAgent = updateOpenAIRealtimeTranscripts(afterUser.state, {
      ...EMPTY_EVENT,
      assistantTranscript: "Tidsplanen flyttades.",
    })
    expect(afterAgent.completed).toBeNull()
    expect(afterAgent.state.output).toBe("Tidsplanen flyttades.")

    const afterDone = updateOpenAIRealtimeTranscripts(afterAgent.state, {
      ...EMPTY_EVENT,
      turnComplete: true,
    })
    expect(afterDone.completed).toEqual({
      input: "Vad minns du?",
      output: "Tidsplanen flyttades.",
    })
    expect(afterDone.state).toEqual({ input: "", output: "" })
    expect(afterDone.orphanOutput).toBeNull()
  })

  it("reports an orphaned output when the turn has no user text", () => {
    const result = updateOpenAIRealtimeTranscripts(
      { input: "", output: "Jag är experten." },
      { ...EMPTY_EVENT, turnComplete: true },
    )
    expect(result.completed).toBeNull()
    expect(result.orphanOutput).toBe("Jag är experten.")
  })

  it("preserves user transcription when the user interrupts the expert", () => {
    const newTurn = updateOpenAIRealtimeTranscripts(
      { input: "", output: "" },
      { ...EMPTY_EVENT, userTranscript: "Jag heter Erik" },
    )
    const interrupted = updateOpenAIRealtimeTranscripts(newTurn.state, {
      ...EMPTY_EVENT,
      interrupted: true,
    })
    expect(interrupted.state).toEqual({
      input: "Jag heter Erik",
      output: "",
    })

    const continued = updateOpenAIRealtimeTranscripts(interrupted.state, {
      ...EMPTY_EVENT,
      userTranscript: " och projektet heter Aurora",
    })
    expect(continued.state).toEqual({
      input: "Jag heter Erik och projektet heter Aurora",
      output: "",
    })
    expect(continued.completed).toBeNull()
  })

  it("creates the greeting turn and the response trigger", () => {
    const messages = openaiRealtimeGreetingMessages("Öppna samtalet.")
    expect(messages).toHaveLength(2)
    expect(JSON.parse(messages[0])).toEqual({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: "Öppna samtalet." }],
      },
    })
    expect(JSON.parse(messages[1])).toEqual({ type: "response.create" })
  })

  it("creates the same user-text turn for tool wakes", () => {
    const messages = openaiRealtimeWakeMessages("[[underlag]]\nBolagsdata")
    expect(messages).toHaveLength(2)
    expect(JSON.parse(messages[0])).toEqual({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: "[[underlag]]\nBolagsdata" }],
      },
    })
    expect(JSON.parse(messages[1])).toEqual({ type: "response.create" })
  })

  it("wraps microphone audio and tool results in protocol messages", () => {
    expect(JSON.parse(openaiRealtimeAudioMessage("pcm"))).toEqual({
      type: "input_audio_buffer.append",
      audio: "pcm",
    })
    const results = openaiRealtimeToolResultMessage([
      { id: "call-1", name: "lookup_company", result: "Bolagsdata" },
      {
        id: "call-2",
        name: "lookup_company",
        result: "Fel",
        isError: true,
      },
    ])
    expect(results).toHaveLength(2)
    expect(JSON.parse(results[0])).toEqual({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: "call-1",
        output: "Bolagsdata",
      },
    })
    expect(JSON.parse(results[1])).toEqual({
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: "call-2",
        output: "Fel",
      },
    })
  })

  it("needs no close or pong messages", () => {
    expect(openaiRealtimeCloseMessage()).toBeNull()
    expect(openaiRealtimePongMessage()).toBeNull()
  })
})
