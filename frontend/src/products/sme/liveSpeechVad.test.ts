import { describe, expect, it } from "vitest"
import { EnergyVad } from "./liveSpeechVad"

function frame(value: number, samples = 240): Float32Array {
  return new Float32Array(samples).fill(value)
}

function calibrate(vad: EnergyVad, energy = 0): void {
  for (let index = 0; index < 20; index += 1) vad.process(frame(energy), 24_000)
}

function speak(vad: EnergyVad, frames: number, energy = 0.2): ReturnType<EnergyVad["process"]>[] {
  return Array.from({ length: frames }, () => vad.process(frame(energy), 24_000))
}

describe("EnergyVad", () => {
  it("retains pre-roll and commits after hangover", () => {
    const vad = new EnergyVad(0.02, 30, 30, 0, 0)
    calibrate(vad)
    expect(vad.process(frame(0.2), 24_000).started).toBe(false)
    const start = vad.process(frame(0.2), 24_000)
    expect(start.started).toBe(true)
    expect(start.frames.length).toBeGreaterThan(1)
    expect(vad.process(frame(0), 24_000).commit).toBe(false)
    expect(vad.process(frame(0), 24_000).commit).toBe(false)
    expect(vad.process(frame(0), 24_000).commit).toBe(true)
  })

  it("calibrates above a quiet noise floor", () => {
    const vad = new EnergyVad(0.001, 30, 30, 0, 0)
    calibrate(vad, 0.005)
    expect(vad.process(frame(0.01), 24_000).started).toBe(false)
    expect(vad.process(frame(0.03), 24_000).started).toBe(false)
    expect(vad.process(frame(0.03), 24_000).started).toBe(true)
  })

  it("keeps frames in the ring until the urgent gate opens STT", () => {
    const vad = new EnergyVad(0.02, 80, 80, 300, 120)
    calibrate(vad)
    const early = speak(vad, 8)
    expect(early.every((result) => !result.started && result.frames.length === 0)).toBe(true)
    const opened = speak(vad, 8).find((result) => result.started)
    expect(opened?.started).toBe(true)
    expect(opened?.frames.length).toBeGreaterThan(1)
  })

  it("abandons speech that never reaches the minimum duration", () => {
    const vad = new EnergyVad(0.02, 80, 30, 300, 120)
    calibrate(vad)
    speak(vad, 16)
    expect(speak(vad, 1, 0)[0].abandon).toBe(false)
    expect(speak(vad, 3, 0).some((result) => result.abandon)).toBe(true)
    expect(speak(vad, 1, 0)[0].commit).toBe(false)
  })

  it("commits a short word once speech passes the minimum", () => {
    const vad = new EnergyVad(0.02, 80, 30, 120, 120)
    calibrate(vad)
    speak(vad, 12)
    expect(speak(vad, 3, 0).some((result) => result.commit)).toBe(true)
  })

  it("commits only after confirmed speech and hangover", () => {
    const vad = new EnergyVad(0.02, 80, 30, 300, 120)
    calibrate(vad)
    speak(vad, 40)
    expect(speak(vad, 2, 0).every((result) => !result.commit && !result.abandon)).toBe(true)
    expect(speak(vad, 2, 0).some((result) => result.commit)).toBe(true)
  })
})
