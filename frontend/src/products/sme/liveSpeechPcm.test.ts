import { describe, expect, it } from "vitest"
import { generationFrame, splitGenerationFrame } from "./liveSpeechPcm"

describe("liveSpeechPcm", () => {
  it("round-trips generation and pcm bytes", () => {
    const pcm = new Uint8Array([1, 2, 3, 4]).buffer
    const framed = generationFrame(9, pcm)
    expect(splitGenerationFrame(framed)).toEqual({
      generation: 9,
      pcm: pcm,
    })
  })

  it("rejects a truncated frame", () => {
    expect(splitGenerationFrame(new ArrayBuffer(3))).toBeNull()
  })
})
