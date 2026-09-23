const DEFAULT_INPUT_SAMPLE_RATE = 16_000

export function pcmSampleRate(format: string): number | null {
  const match = /^pcm_(\d+)$/i.exec(format.trim())
  if (!match) return null
  const rate = Number(match[1])
  return Number.isFinite(rate) && rate > 0 ? rate : null
}

export async function decodeLiveVoiceFrame(data: unknown): Promise<string | null> {
  if (typeof data === "string") return data
  if (data instanceof ArrayBuffer) return new TextDecoder().decode(data)
  if (data instanceof Blob) return data.text()
  return null
}

export function encodePcm16Base64(
  source: Float32Array,
  sourceSampleRate: number,
  targetSampleRate = DEFAULT_INPUT_SAMPLE_RATE,
): string {
  const outputLength = Math.max(
    1,
    Math.round(source.length * targetSampleRate / sourceSampleRate),
  )
  const bytes = new Uint8Array(outputLength * 2)
  const view = new DataView(bytes.buffer)
  const ratio = sourceSampleRate / targetSampleRate

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
