import {
  createRingbackSamples,
  decodeLiveVoiceFrame,
  decodePcm16Base64,
  encodePcm16Base64,
} from "@/components/chat/liveVoiceAudio"

const INPUT_SAMPLE_RATE = 16_000
const OUTPUT_SAMPLE_RATE = 24_000

export type GeminiLiveServerEvent = {
  setupComplete: boolean
  interrupted: boolean
  audioChunks: string[]
  inputTranscript: string
  outputTranscript: string
  turnComplete: boolean
  toolCalls: GeminiLiveToolCall[]
}

type UnknownRecord = Record<string, unknown>

export type GeminiLiveToolCall = {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export type GeminiLiveTranscriptState = {
  input: string
  output: string
}

export function updateGeminiLiveTranscripts(
  state: GeminiLiveTranscriptState,
  event: GeminiLiveServerEvent,
): {
  state: GeminiLiveTranscriptState
  completed: GeminiLiveTranscriptState | null
} {
  const startsNewUserTurn = Boolean(event.inputTranscript && state.output)
  const next = {
    input: (startsNewUserTurn ? "" : state.input) + event.inputTranscript,
    output:
      (event.interrupted || startsNewUserTurn ? "" : state.output) +
      event.outputTranscript,
  }
  if (!event.turnComplete) return { state: next, completed: null }
  const completed = {
    input: next.input.trim(),
    output: next.output.trim(),
  }
  return {
    state: { input: "", output: "" },
    completed: completed.input && completed.output ? completed : null,
  }
}

function asRecord(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null
    ? (value as UnknownRecord)
    : null
}

export async function decodeGeminiLiveFrame(data: unknown): Promise<string | null> {
  return decodeLiveVoiceFrame(data)
}

export function parseGeminiLiveMessage(raw: string): GeminiLiveServerEvent {
  const message = asRecord(JSON.parse(raw))
  const serverContent = asRecord(message?.serverContent)
  const modelTurn = asRecord(serverContent?.modelTurn)
  const inputTranscription = asRecord(serverContent?.inputTranscription)
  const outputTranscription = asRecord(serverContent?.outputTranscription)
  const parts = Array.isArray(modelTurn?.parts) ? modelTurn.parts : []
  const audioChunks: string[] = []
  const toolCall = asRecord(message?.toolCall)
  const functionCalls = Array.isArray(toolCall?.functionCalls)
    ? toolCall.functionCalls
    : []
  const toolCalls: GeminiLiveToolCall[] = []

  for (const partValue of parts) {
    const part = asRecord(partValue)
    const inlineData = asRecord(part?.inlineData)
    if (typeof inlineData?.data === "string") {
      audioChunks.push(inlineData.data)
    }
  }
  for (const callValue of functionCalls) {
    const call = asRecord(callValue)
    const argumentsValue = asRecord(call?.args)
    if (
      typeof call?.id === "string" &&
      typeof call.name === "string" &&
      argumentsValue
    ) {
      toolCalls.push({
        id: call.id,
        name: call.name,
        arguments: argumentsValue,
      })
    }
  }

  return {
    setupComplete: message?.setupComplete !== undefined,
    interrupted: serverContent?.interrupted === true,
    audioChunks,
    inputTranscript:
      typeof inputTranscription?.text === "string"
        ? inputTranscription.text
        : "",
    outputTranscript:
      typeof outputTranscription?.text === "string"
        ? outputTranscription.text
        : "",
    turnComplete: serverContent?.turnComplete === true,
    toolCalls,
  }
}

export function liveSetupMessage(model: string, voice: string): string {
  return JSON.stringify({
    setup: {
      model: `models/${model}`,
      generationConfig: {
        responseModalities: ["AUDIO"],
        speechConfig: {
          voiceConfig: {
            prebuiltVoiceConfig: {
              voiceName: voice,
            },
          },
        },
      },
    },
  })
}

export function liveAudioMessage(data: string): string {
  return JSON.stringify({
    realtimeInput: {
      audio: {
        data,
        mimeType: `audio/pcm;rate=${INPUT_SAMPLE_RATE}`,
      },
    },
  })
}

export function liveClientContentMessage(text: string): string {
  return JSON.stringify({
    clientContent: {
      turns: [{ role: "user", parts: [{ text }] }],
      turnComplete: true,
    },
  })
}

export function liveToolResponseMessage(
  responses: Array<{ id: string; name: string; result: string }>,
): string {
  return JSON.stringify({
    toolResponse: {
      functionResponses: responses.map((response) => ({
        id: response.id,
        name: response.name,
        response: { result: response.result },
      })),
    },
  })
}

export const GEMINI_OUTPUT_SAMPLE_RATE = OUTPUT_SAMPLE_RATE
export const GEMINI_INPUT_SAMPLE_RATE = INPUT_SAMPLE_RATE

export { createRingbackSamples, decodePcm16Base64, encodePcm16Base64 }
