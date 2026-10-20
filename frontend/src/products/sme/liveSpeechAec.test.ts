import { describe, expect, it, vi } from "vitest"
import { appliedEchoCancellation } from "./liveSpeechAec"

describe("appliedEchoCancellation", () => {
  it("reads the applied browser setting", () => {
    const stream = {
      getAudioTracks: () => [{ getSettings: () => ({ echoCancellation: true }) }],
    } as unknown as MediaStream
    expect(appliedEchoCancellation(stream)).toBe(true)
  })

  it("fails closed when the browser disabled AEC", () => {
    const stream = {
      getAudioTracks: () => [{ getSettings: () => ({ echoCancellation: false }) }],
    } as unknown as MediaStream
    expect(appliedEchoCancellation(stream)).toBe(false)
  })

  it("treats a missing setting as unknown", () => {
    const stream = {
      getAudioTracks: () => [{ stop: vi.fn() }],
    } as unknown as MediaStream
    expect(appliedEchoCancellation(stream)).toBeNull()
  })
})
