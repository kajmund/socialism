import { describe, expect, it } from "vitest"

import { SpeechVadPipeline } from "./speechVadPipeline"
import type { SpeechVad } from "./speechVad"

function recordingVad(calls: Float32Array[], results: Array<{ started?: boolean; frames: number; abandon?: boolean; commit?: boolean }>) {
  const vad: SpeechVad = {
    reset: () => undefined,
    push: (frame: Float32Array) => {
      calls.push(frame)
      const result = results.shift() ?? { frames: 0 }
      return Promise.resolve({
        started: result.started ?? false,
        frames: Array.from({ length: result.frames }, () => new Float32Array(1)),
        abandon: result.abandon ?? false,
        commit: result.commit ?? false,
      })
    },
  }
  return vad
}

describe("SpeechVadPipeline", () => {
  it("buffers frames before the vad attaches and replays them in order", async () => {
    const calls: Float32Array[] = []
    const vad = recordingVad(calls, [{ started: true, frames: 1 }])
    const frameCounts: number[] = []
    const pipeline = new SpeechVadPipeline(
      {
        onFrames: (frames) => frameCounts.push(frames.length),
        onAbandon: () => undefined,
        onCommit: () => undefined,
      },
      250,
      () => Promise.resolve(vad),
    )

    pipeline.feed(new Float32Array(4), 24_000)
    pipeline.feed(new Float32Array(8), 24_000)
    expect(calls).toHaveLength(0)

    await pipeline.attach({})
    expect(calls.map((frame) => frame.length)).toEqual([4, 8])
    expect(frameCounts).toEqual([1])
  })

  it("trims the pre-roll buffer to the configured window", async () => {
    const calls: Float32Array[] = []
    const vad = recordingVad(calls, [])
    const pipeline = new SpeechVadPipeline(
      {
        onFrames: () => undefined,
        onAbandon: () => undefined,
        onCommit: () => undefined,
      },
      250,
      () => Promise.resolve(vad),
    )

    // 250 ms at 24 kHz = 6000 samples; four 2000-sample frames exceed the
    // window, so the oldest frame is dropped before replay.
    pipeline.feed(new Float32Array(2000), 24_000)
    pipeline.feed(new Float32Array(2000), 24_000)
    pipeline.feed(new Float32Array(2000), 24_000)
    pipeline.feed(new Float32Array(2000), 24_000)

    await pipeline.attach({})
    expect(calls.map((frame) => frame.length)).toEqual([2000, 2000, 2000])
  })
})
