import { describe, expect, it } from "vitest"
import { resample, SileroGate } from "./sileroGate"

describe("SileroGate", () => {
  it("asks Silero once per 512 samples at 16 kHz", async () => {
    const windows: number[] = []
    const gate = new SileroGate(async (window) => {
      windows.push(window.length)
      return 0.9
    })
    expect(await gate.speech(new Float32Array(256), 16_000)).toBe(false)
    expect(windows).toEqual([])
    expect(await gate.speech(new Float32Array(256), 16_000)).toBe(true)
    expect(windows).toEqual([512])
  })

  it("treats a low probability as silence", async () => {
    const gate = new SileroGate(async () => 0.2)
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(false)
  })

  it("resamples 24 kHz frames down to 16 kHz", () => {
    const frame = new Float32Array(720)
    expect(resample(frame, 24_000, 16_000)).toHaveLength(480)
  })
})
