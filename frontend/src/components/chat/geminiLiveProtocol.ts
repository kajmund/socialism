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
  if (typeof data === "string") return data
  if (data instanceof ArrayBuffer) return new TextDecoder().decode(data)
  if (data instanceof Blob) return data.text()
  return null
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

export function encodePcm16Base64(
  source: Float32Array,
  sourceSampleRate: number,
): string {
  const outputLength = Math.max(
    1,
    Math.round(source.length * INPUT_SAMPLE_RATE / sourceSampleRate),
  )
  const bytes = new Uint8Array(outputLength * 2)
  const view = new DataView(bytes.buffer)
  const ratio = sourceSampleRate / INPUT_SAMPLE_RATE

  for (let index = 0; index < outputLength; index += 1) {
    const position = index * ratio
    const leftIndex = Math.min(Math.floor(position), source.length - 1)
    const rightIndex = Math.min(leftIndex + 1, source.length - 1)
    const fraction = position - leftIndex
    const sample =
      source[leftIndex] + (source[rightIndex] - source[leftIndex]) * fraction
    const clamped = Math.max(-1, Math.min(1, sample))
    const pcm = clamped < 0
      ? Math.round(clamped * 0x8000)
      : Math.round(clamped * 0x7fff)
    view.setInt16(index * 2, pcm, true)
  }

  let binary = ""
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index])
  }
  return btoa(binary)
}

export function decodePcm16Base64(data: string): Float32Array {
  const binary = atob(data)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  const view = new DataView(bytes.buffer)
  const samples = new Float32Array(Math.floor(bytes.length / 2))
  for (let index = 0; index < samples.length; index += 1) {
    const value = view.getInt16(index * 2, true)
    samples[index] = value < 0 ? value / 0x8000 : value / 0x7fff
  }
  return samples
}

export function createRingbackSamples(sampleRate: number): Float32Array {
  const duration = 2.5
  const samples = new Float32Array(Math.ceil(sampleRate * duration))
  const pulses: Array<[number, number]> = [
    [0, 0.42],
    [0.58, 1],
    [1.48, 1.9],
    [2.06, 2.48],
  ]
  const fadeDuration = 0.015
  for (let index = 0; index < samples.length; index += 1) {
    const time = index / sampleRate
    const pulse = pulses.find(([start, end]) => time >= start && time < end)
    if (!pulse) continue
    const [start, end] = pulse
    const envelope = Math.min(
      1,
      (time - start) / fadeDuration,
      (end - time) / fadeDuration,
    )
    samples[index] =
      envelope *
      0.12 *
      (Math.sin(2 * Math.PI * 425 * time) +
        Math.sin(2 * Math.PI * 450 * time))
  }
  return samples
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
