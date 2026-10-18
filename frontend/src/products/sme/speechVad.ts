import { turnVadFromConfig, type VadResult } from "./turnVad"

export type SpeechVad = {
  push(frame: Float32Array, sampleRate: number): Promise<VadResult>
  reset(): void
}

export type SileroThresholds = {
  threshold: number
  exitThreshold: number
}

export async function createSpeechVad(config: unknown): Promise<SpeechVad> {
  const [{ SileroGate }, { loadSileroModel }] = await Promise.all([
    import("./sileroGate"),
    import("./sileroModel"),
  ])
  const turn = turnVadFromConfig(config)
  const model = await loadSileroModel()
  model.reset()
  const { threshold, exitThreshold } = sileroThresholdsFromConfig(config)
  const gate = new SileroGate(
    (window) => model.probability(window),
    threshold,
    exitThreshold,
  )
  return {
    reset() {
      turn.resetTurn()
      gate.reset()
      model.reset()
    },
    push(frame, sampleRate) {
      return gate.speech(frame, sampleRate).then((speech) => turn.push(speech, frame, sampleRate))
    },
  }
}

export function sileroThresholdsFromConfig(config: unknown): SileroThresholds {
  const vad = config && typeof config === "object" ? config as Record<string, unknown> : {}
  return {
    threshold: finiteNumber(vad.silero_threshold, 0.5),
    exitThreshold: finiteNumber(vad.silero_exit_threshold, 0.35),
  }
}

/**
 * Warm the shared Silero session before the user connects so the first
 * utterance is not lost. Kept dynamic so onnxruntime-web stays code-split.
 */
export function preloadSpeechVad(): Promise<unknown> {
  return import("./sileroModel").then(({ loadSileroModel }) => loadSileroModel())
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}
