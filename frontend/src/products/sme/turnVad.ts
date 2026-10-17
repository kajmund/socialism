export type VadResult = {
  frames: Float32Array[]
  started: boolean
  commit: boolean
  abandon: boolean
}

/** Turn segmentation. Speech itself comes from Silero, not from audio energy. */
export class TurnVad {
  private readonly preroll: Float32Array[] = []
  private speaking = false
  private above = 0
  private silenceMs = 0
  private speechMs = 0
  private opened = false
  private confirmed = false

  constructor(
    private readonly prerollMs: number,
    private readonly hangoverMs: number,
    private readonly minSpeechMs = 120,
    private readonly urgentMs = 120,
  ) {}

  push(speech: boolean, frame: Float32Array, sampleRate: number): VadResult {
    const durationMs = frame.length / sampleRate * 1000
    if (!this.speaking) {
      this.preroll.push(frame)
      trimPreroll(this.preroll, this.prerollMs, sampleRate)
      this.above = speech ? this.above + 1 : 0
      if (this.above < 2) return idle()
      this.speaking = true
      this.speechMs = durationMs * this.above
      this.silenceMs = 0
      return this.release(false)
    }
    if (speech) {
      this.silenceMs = 0
      this.speechMs += durationMs
      this.preroll.push(frame)
      return this.release(false)
    }
    this.silenceMs += durationMs
    if (this.silenceMs < this.hangoverMs) {
      if (!this.opened) {
        this.preroll.push(frame)
        return idle()
      }
      return { frames: [frame], started: false, commit: false, abandon: false }
    }
    const opened = this.opened
    const confirmed = this.confirmed
    this.resetTurn()
    if (confirmed) return { frames: opened ? [frame] : [], started: false, commit: true, abandon: false }
    return { frames: [], started: false, commit: false, abandon: opened }
  }

  resetTurn(): void {
    this.speaking = false
    this.above = 0
    this.silenceMs = 0
    this.speechMs = 0
    this.opened = false
    this.confirmed = false
    this.preroll.length = 0
  }

  private release(commit: boolean): VadResult {
    const openAt = Math.min(this.urgentMs, this.minSpeechMs)
    if (!this.opened && this.speechMs >= openAt) {
      this.opened = true
      this.confirmed = this.speechMs >= this.minSpeechMs
      return { frames: this.preroll.splice(0), started: true, commit, abandon: false }
    }
    if (this.speechMs >= this.minSpeechMs) this.confirmed = true
    if (!this.opened) return idle()
    const frames = this.preroll.splice(0)
    return { frames, started: false, commit, abandon: false }
  }
}

function idle(): VadResult {
  return { frames: [], started: false, commit: false, abandon: false }
}

function trimPreroll(frames: Float32Array[], maxMs: number, sampleRate: number): void {
  let samples = frames.reduce((total, frame) => total + frame.length, 0)
  const maxSamples = sampleRate * maxMs / 1000
  while (samples > maxSamples && frames.length > 1) {
    samples -= frames.shift()?.length ?? 0
  }
}

export function turnVadFromConfig(config: unknown): TurnVad {
  const vad = config && typeof config === "object" ? config as Record<string, unknown> : {}
  return new TurnVad(
    finiteNumber(vad.preroll_ms, 250),
    finiteNumber(vad.hangover_ms, 600),
    finiteNumber(vad.min_speech_ms, 120),
    finiteNumber(vad.urgent_ms, 120),
  )
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}
