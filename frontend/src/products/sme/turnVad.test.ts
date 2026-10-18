import { describe, expect, it } from "vitest"
import { TurnVad, turnVadFromConfig } from "./turnVad"

function frame(): Float32Array {
  return new Float32Array(240)
}

function push(vad: TurnVad, frames: number, speech: boolean) {
  return Array.from({ length: frames }, () => vad.push(speech, frame(), 24_000))
}

describe("TurnVad", () => {
  it("retains pre-roll and commits after hangover", () => {
    const vad = new TurnVad(30, 30, 0, 0)
    push(vad, 4, false)
    expect(vad.push(true, frame(), 24_000).started).toBe(false)
    const start = vad.push(true, frame(), 24_000)
    expect(start.started).toBe(true)
    expect(start.frames.length).toBeGreaterThan(1)
    expect(vad.push(false, frame(), 24_000).commit).toBe(false)
    expect(vad.push(false, frame(), 24_000).commit).toBe(false)
    expect(vad.push(false, frame(), 24_000).commit).toBe(true)
  })

  it("keeps frames in the ring until the urgent gate opens STT", () => {
    const vad = new TurnVad(80, 80, 300, 120)
    const early = push(vad, 8, true)
    expect(early.every((result) => !result.started && result.frames.length === 0)).toBe(true)
    const opened = push(vad, 8, true).find((result) => result.started)
    expect(opened?.started).toBe(true)
    expect(opened?.frames.length).toBeGreaterThan(1)
  })

  it("abandons speech that never reaches the minimum duration", () => {
    const vad = new TurnVad(80, 30, 300, 120)
    push(vad, 16, true)
    expect(push(vad, 1, false)[0].abandon).toBe(false)
    expect(push(vad, 3, false).some((result) => result.abandon)).toBe(true)
    expect(push(vad, 1, false)[0].commit).toBe(false)
  })

  it("commits a short word once speech passes the minimum", () => {
    const vad = new TurnVad(80, 30, 120, 120)
    push(vad, 12, true)
    expect(push(vad, 3, false).some((result) => result.commit)).toBe(true)
  })

  it("commits only after confirmed speech and hangover", () => {
    const vad = new TurnVad(80, 30, 300, 120)
    push(vad, 40, true)
    expect(push(vad, 2, false).every((result) => !result.commit && !result.abandon)).toBe(true)
    expect(push(vad, 2, false).some((result) => result.commit)).toBe(true)
  })

  it("waits for the server hangover before sending the utterance", () => {
    const vad = turnVadFromConfig({
      preroll_ms: 30,
      hangover_ms: 600,
      min_speech_ms: 0,
      urgent_ms: 0,
    })
    push(vad, 4, true)
    expect(push(vad, 50, false).some((result) => result.commit)).toBe(false)
    expect(push(vad, 15, false).some((result) => result.commit)).toBe(true)
  })
})
