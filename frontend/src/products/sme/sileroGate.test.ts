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

  it("keeps speech open between the thresholds and closes below the exit", async () => {
    const probabilities = [0.6, 0.45, 0.45, 0.2]
    let index = 0
    const gate = new SileroGate(async () => probabilities[index++])
    const results = []
    for (let i = 0; i < probabilities.length; i += 1) {
      results.push(await gate.speech(new Float32Array(512), 16_000))
    }
    expect(results).toEqual([true, true, true, false])
  })

  it("smoothes a single low window so speech does not flicker", async () => {
    const probabilities = [0.9, 0.2]
    let index = 0
    const gate = new SileroGate(async () => probabilities[index++])
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(true)
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(true)
  })

  it("honors configured start and exit thresholds", async () => {
    const probabilities = [0.5, 0.7]
    let index = 0
    const gate = new SileroGate(async () => probabilities[index++], 0.6, 0.3)
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(false)
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(true)
  })

  it("resets smoothing and speech state", async () => {
    let value = 0.9
    const gate = new SileroGate(async () => value)
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(true)
    value = 0.2
    gate.reset()
    expect(await gate.speech(new Float32Array(512), 16_000)).toBe(false)
  })
})
