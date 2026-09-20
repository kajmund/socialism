import { describe, expect, it } from "vitest"
import {
  createRingbackSamples,
  decodeGeminiLiveFrame,
  decodePcm16Base64,
  encodePcm16Base64,
  liveClientContentMessage,
  liveSetupMessage,
  liveToolResponseMessage,
  parseGeminiLiveMessage,
  updateGeminiLiveTranscripts,
} from "@/components/chat/geminiLiveProtocol"

describe("Gemini Live protocol", () => {
  it("decodes binary WebSocket JSON frames", async () => {
    const frame = new TextEncoder().encode('{"setupComplete":{}}').buffer
    expect(await decodeGeminiLiveFrame(frame)).toBe('{"setupComplete":{}}')
  })

  it("converts microphone samples to little-endian PCM16", () => {
    const encoded = encodePcm16Base64(
      new Float32Array([-1, -0.5, 0, 0.5, 1]),
      16_000,
    )
    const decoded = decodePcm16Base64(encoded)

    expect(decoded).toHaveLength(5)
    expect(decoded[0]).toBe(-1)
    expect(decoded[1]).toBe(-0.5)
    expect(decoded[2]).toBe(0)
    expect(decoded[3]).toBeCloseTo(0.5, 4)
    expect(decoded[4]).toBe(1)
  })

  it("creates four audible ring pulses with silence between them", () => {
    const samples = createRingbackSamples(24_000)
    const firstPulse = samples.slice(1, Math.round(0.4 * 24_000))

    expect(samples).toHaveLength(60_000)
    expect(firstPulse.some((sample) => Math.abs(sample) > 0.01)).toBe(true)
    expect(samples[Math.round(1.2 * 24_000)]).toBe(0)
  })

  it("extracts setup, interruption, and audio chunks", () => {
    const event = parseGeminiLiveMessage(
      JSON.stringify({
        setupComplete: {},
        serverContent: {
          interrupted: true,
          inputTranscription: { text: "Hallå" },
          outputTranscription: { text: "Hej" },
          turnComplete: true,
          modelTurn: {
            parts: [
              { inlineData: { data: "first", mimeType: "audio/pcm;rate=24000" } },
              { text: "ignored" },
              { inlineData: { data: "second", mimeType: "audio/pcm;rate=24000" } },
            ],
          },
        },
      }),
    )

    expect(event).toEqual({
      setupComplete: true,
      interrupted: true,
      audioChunks: ["first", "second"],
      inputTranscript: "Hallå",
      outputTranscript: "Hej",
      turnComplete: true,
      toolCalls: [],
    })
  })

  it("parses tool calls and creates matching responses", () => {
    const event = parseGeminiLiveMessage(
      JSON.stringify({
        toolCall: {
          functionCalls: [
            {
              id: "call-1",
              name: "lookup_company",
              args: { orgnr: "556000-0000" },
            },
          ],
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
        liveToolResponseMessage([
          { id: "call-1", name: "lookup_company", result: "Bolagsdata" },
        ]),
      ),
    ).toEqual({
      toolResponse: {
        functionResponses: [
          {
            id: "call-1",
            name: "lookup_company",
            response: { result: "Bolagsdata" },
          },
        ],
      },
    })
  })

  it("preserves user transcription when the user interrupts the expert", () => {
    const newTurn = updateGeminiLiveTranscripts(
      { input: "Tidigare fråga", output: "Ett avbrutet expertsvar" },
      {
        setupComplete: false,
        interrupted: false,
        audioChunks: [],
        inputTranscript: "Jag heter Erik",
        outputTranscript: "",
        turnComplete: false,
        toolCalls: [],
      },
    )
    const interrupted = updateGeminiLiveTranscripts(newTurn.state, {
      setupComplete: false,
      interrupted: true,
      audioChunks: [],
      inputTranscript: " och projektet heter Aurora",
      outputTranscript: "",
      turnComplete: false,
      toolCalls: [],
    })
    expect(interrupted.state).toEqual({
      input: "Jag heter Erik och projektet heter Aurora",
      output: "",
    })

    const completed = updateGeminiLiveTranscripts(interrupted.state, {
      setupComplete: false,
      interrupted: false,
      audioChunks: [],
      inputTranscript: "",
      outputTranscript: "Jag kommer ihåg det.",
      turnComplete: true,
      toolCalls: [],
    })
    expect(completed.completed).toEqual({
      input: "Jag heter Erik och projektet heter Aurora",
      output: "Jag kommer ihåg det.",
    })
  })

  it("creates the initial complete client turn", () => {
    expect(JSON.parse(liveClientContentMessage("Öppna samtalet."))).toEqual({
      clientContent: {
        turns: [
          {
            role: "user",
            parts: [{ text: "Öppna samtalet." }],
          },
        ],
        turnComplete: true,
      },
    })
  })

  it("keeps the client setup free of system instructions", () => {
    expect(JSON.parse(liveSetupMessage("gemini-3.8-live", "Algenib"))).toEqual({
      setup: {
        model: "models/gemini-3.8-live",
        generationConfig: {
          responseModalities: ["AUDIO"],
          speechConfig: {
            voiceConfig: {
              prebuiltVoiceConfig: {
                voiceName: "Algenib",
              },
            },
          },
        },
      },
    })
  })
})
