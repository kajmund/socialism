import { createSpeechVad, type SpeechVad } from "./speechVad"
import type { VadResult } from "./turnVad"

export type VadCallbacks = {
  onStarted?: () => void
  onFrames: (frames: Float32Array[], sampleRate: number) => void
  onAbandon: () => void
  onCommit: () => void
  onError?: () => void
}

/**
 * VAD-gated frame sink shared by single-expert and group voice.
 *
 * Buffers a short pre-roll while the Silero session loads, then runs frames
 * through the VAD in a serialized chain and reports started/frames/abandon/
 * commit to the caller, which owns the wire protocol.
 */
export class SpeechVadPipeline {
  private vad: SpeechVad | null = null
  private hearing: Promise<void> = Promise.resolve()
  private preVadFrames: Float32Array[] = []
  private preVadSamples = 0
  private failed = false
  private lastRate = 48_000

  constructor(
    private readonly callbacks: VadCallbacks,
    private readonly prerollMs = 250,
    private readonly create: (config: unknown) => Promise<SpeechVad> = createSpeechVad,
  ) {}

  get ready(): boolean {
    return this.vad !== null
  }

  async attach(config: unknown): Promise<void> {
    this.vad = await this.create(config)
    const buffered = this.preVadFrames.splice(0)
    this.preVadSamples = 0
    for (const frame of buffered) this.feed(frame, this.lastRate)
    await this.hearing
  }

  feed(frame: Float32Array, sampleRate: number): void {
    this.lastRate = sampleRate
    const vad = this.vad
    if (vad === null) {
      this.preVadFrames.push(frame)
      this.preVadSamples += frame.length
      const max = sampleRate * (this.prerollMs / 1000)
      while (this.preVadSamples > max && this.preVadFrames.length > 1) {
        this.preVadSamples -= this.preVadFrames.shift()?.length ?? 0
      }
      return
    }
    this.hearing = this.hearing
      .then(() => vad.push(frame, sampleRate))
      .then((result: VadResult) => {
        if (result.started) this.callbacks.onStarted?.()
        if (result.frames.length > 0) this.callbacks.onFrames(result.frames, sampleRate)
        if (result.abandon) this.callbacks.onAbandon()
        if (result.commit) this.callbacks.onCommit()
      })
      .catch(() => {
        if (this.failed) return
        this.failed = true
        this.callbacks.onError?.()
      })
  }

  reset(): void {
    this.vad?.reset()
    this.preVadFrames.length = 0
    this.preVadSamples = 0
  }
}
