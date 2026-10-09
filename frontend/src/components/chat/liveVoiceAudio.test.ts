import { describe, expect, it } from "vitest"
import { decodePcm16, encodePcm16 } from "./liveVoiceAudio"

describe("Live Speech PCM", () => {
  it("resamples Float32 audio to little-endian PCM16", () => {
    const encoded = encodePcm16(new Float32Array([-1, 0, 1]), 24_000, 24_000)
    const view = new DataView(encoded)
    expect(view.getInt16(0, true)).toBe(-32768)
    expect(view.getInt16(2, true)).toBe(0)
    expect(view.getInt16(4, true)).toBe(32767)
    expect(Array.from(decodePcm16(encoded))).toEqual([-1, 0, 1])
  })

  it("resamples without returning an empty frame", () => {
    const encoded = encodePcm16(new Float32Array([0.25]), 48_000, 24_000)
    expect(encoded.byteLength).toBe(2)
  })
})
