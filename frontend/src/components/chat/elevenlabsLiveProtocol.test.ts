import { describe, expect, it } from "vitest"
import {
  elevenLabsPongMessage,
  elevenLabsToolResultMessage,
  elevenLabsUserAudioMessage,
  parseElevenLabsMessage,
  updateElevenLabsTranscripts,
} from "@/components/chat/elevenlabsLiveProtocol"
import { pcmSampleRate } from "@/components/chat/liveVoiceAudio"

describe("ElevenLabs live protocol", () => {
  it("parses ping, audio, transcripts, interruption, and metadata", () => {
    expect(
      parseElevenLabsMessage(
        JSON.stringify({
          type: "ping",
          ping_event: { event_id: 7, ping_ms: 12 },
        }),
      ),
    ).toEqual({
      sessionReady: false,
      interrupted: false,
      audioChunks: [],
      inputFormat: null,
      outputFormat: null,
      ping: { eventId: 7, pingMs: 12 },
      toolCalls: [],
      userTranscript: "",
      assistantTranscript: "",
    })

    expect(
      parseElevenLabsMessage(
        JSON.stringify({
          type: "audio",
          audio_event: { audio_base_64: "chunk", event_id: 1 },
        }),
      ).audioChunks,
    ).toEqual(["chunk"])

    expect(
      parseElevenLabsMessage(
        JSON.stringify({
          type: "user_transcript",
          user_transcription_event: { user_transcript: "Hallå", event_id: 2 },
        }),
      ).userTranscript,
    ).toBe("Hallå")

    expect(
      parseElevenLabsMessage(
        JSON.stringify({
          type: "agent_response",
          agent_response_event: { agent_response: "Hej", event_id: 3 },
        }),
      ).assistantTranscript,
    ).toBe("Hej")

    expect(
      parseElevenLabsMessage(
        JSON.stringify({
          type: "interruption",
          interruption_event: { event_id: 4 },
        }),
      ).interrupted,
    ).toBe(true)

    expect(
      parseElevenLabsMessage(
        JSON.stringify({
          type: "conversation_initiation_metadata",
          conversation_initiation_metadata_event: {
            conversation_id: "conv_1",
            user_input_audio_format: "pcm_16000",
            agent_output_audio_format: "pcm_44100",
          },
        }),
      ),
    ).toMatchObject({
      sessionReady: true,
      inputFormat: "pcm_16000",
      outputFormat: "pcm_44100",
    })
  })

  it("parses client tool calls and builds tool results plus pong", () => {
    const event = parseElevenLabsMessage(
      JSON.stringify({
        type: "client_tool_call",
        client_tool_call: {
          tool_name: "lookup_company",
          tool_call_id: "call-1",
          parameters: { orgnr: "556000-0000" },
          event_id: 9,
        },
      }),
    )

    expect(event.toolCalls).toEqual([
      {
        id: "call-1",
        name: "lookup_company",
        arguments: { orgnr: "556000-0000" },
      },
    ])
    expect(
      JSON.parse(
        elevenLabsToolResultMessage([
          { id: "call-1", result: "Bolagsdata" },
        ])[0],
      ),
    ).toEqual({
      type: "client_tool_result",
      tool_call_id: "call-1",
      result: "Bolagsdata",
      is_error: false,
    })
    expect(JSON.parse(elevenLabsPongMessage(7))).toEqual({
      type: "pong",
      event_id: 7,
    })
    expect(JSON.parse(elevenLabsUserAudioMessage("pcm"))).toEqual({
      user_audio_chunk: "pcm",
    })
  })

  it("pairs user_transcript with the following agent_response for memory", () => {
    const afterUser = updateElevenLabsTranscripts(
      { input: "", output: "" },
      {
        sessionReady: false,
        interrupted: false,
        audioChunks: [],
        inputFormat: null,
        outputFormat: null,
        ping: null,
        toolCalls: [],
        userTranscript: "Vad minns du?",
        assistantTranscript: "",
      },
    )
    expect(afterUser.completed).toBeNull()
    expect(afterUser.state.input).toBe("Vad minns du?")

    const afterAgent = updateElevenLabsTranscripts(afterUser.state, {
      sessionReady: false,
      interrupted: false,
      audioChunks: [],
      inputFormat: null,
      outputFormat: null,
      ping: null,
      toolCalls: [],
      userTranscript: "",
      assistantTranscript: "Tidsplanen flyttades.",
    })
    expect(afterAgent.completed).toEqual({
      input: "Vad minns du?",
      output: "Tidsplanen flyttades.",
    })
    expect(afterAgent.state).toEqual({ input: "", output: "" })
  })

  it("does not record the agent greeting before the user has spoken", () => {
    const greeting = updateElevenLabsTranscripts(
      { input: "", output: "" },
      {
        sessionReady: false,
        interrupted: false,
        audioChunks: [],
        inputFormat: null,
        outputFormat: null,
        ping: null,
        toolCalls: [],
        userTranscript: "",
        assistantTranscript: "Ja, det är Röstexpert.",
      },
    )
    expect(greeting.completed).toBeNull()
    expect(greeting.state.output).toBe("Ja, det är Röstexpert.")
  })

  it("clears pending agent text on interruption", () => {
    const interrupted = updateElevenLabsTranscripts(
      { input: "Hallå", output: "Ett avbrutet svar" },
      {
        sessionReady: false,
        interrupted: true,
        audioChunks: [],
        inputFormat: null,
        outputFormat: null,
        ping: null,
        toolCalls: [],
        userTranscript: "",
        assistantTranscript: "",
      },
    )
    expect(interrupted.state).toEqual({ input: "Hallå", output: "" })
    expect(interrupted.completed).toBeNull()
  })

  it("reads pcm sample rates from session audio formats", () => {
    expect(pcmSampleRate("pcm_16000")).toBe(16_000)
    expect(pcmSampleRate("pcm_24000")).toBe(24_000)
    expect(pcmSampleRate("pcm_44100")).toBe(44_100)
    expect(pcmSampleRate("ulaw_8000")).toBeNull()
  })
})
