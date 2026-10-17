import { turnVadFromConfig, type VadResult } from "./turnVad"

export type SpeechVad = {
  push(frame: Float32Array, sampleRate: number): Promise<VadResult>
  reset(): void
}

export async function createSpeechVad(config: unknown): Promise<SpeechVad> {
  const [{ SileroGate }, { loadSileroModel }] = await Promise.all([
    import("./sileroGate"),
    import("./sileroModel"),
  ])
  const turn = turnVadFromConfig(config)
  const model = await loadSileroModel()
  const gate = new SileroGate((window) => model.probability(window))
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
