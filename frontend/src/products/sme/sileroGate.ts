const WINDOW = 512
const TARGET_RATE = 16_000

export type SpeechProbability = (window: Float32Array) => Promise<number>

/** Buffers microphone audio into Silero's 16 kHz windows. */
export class SileroGate {
  private pending: Float32Array<ArrayBufferLike> = new Float32Array(0)
  private speaking = false

  constructor(
    private readonly probability: SpeechProbability,
    private readonly threshold = 0.5,
  ) {}

  reset(): void {
    this.pending = new Float32Array(0)
    this.speaking = false
  }

  async speech(frame: Float32Array, sampleRate: number): Promise<boolean> {
    const samples = resample(frame, sampleRate, TARGET_RATE)
    this.pending = concat(this.pending, samples)
    while (this.pending.length >= WINDOW) {
      const window = this.pending.slice(0, WINDOW)
      this.pending = this.pending.slice(WINDOW)
      this.speaking = await this.probability(window) >= this.threshold
    }
    return this.speaking
  }
}

function concat(left: Float32Array, right: Float32Array): Float32Array {
  if (left.length === 0) return right
  const joined = new Float32Array(left.length + right.length)
  joined.set(left, 0)
  joined.set(right, left.length)
  return joined
}

export function resample(frame: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate || frame.length === 0) return frame
  const outLength = Math.max(1, Math.round(frame.length * toRate / fromRate))
  const out = new Float32Array(outLength)
  const scale = fromRate / toRate
  for (let index = 0; index < outLength; index += 1) {
    const position = index * scale
    const left = Math.floor(position)
    const right = Math.min(left + 1, frame.length - 1)
    const fraction = position - left
    out[index] = frame[left] * (1 - fraction) + frame[right] * fraction
  }
  return out
}
