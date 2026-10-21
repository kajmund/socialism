import { describe, expect, it, vi } from "vitest"
import { PcmQueue } from "./pcmQueue"

describe("PcmQueue", () => {
  it("stops queued sources so a cancelled generation cannot finish playing", () => {
    const queue = new PcmQueue()
    const source = { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null }
    const context = {
      createBuffer: () => ({ getChannelData: () => ({ set: vi.fn() }), duration: 0.2 }),
      createBufferSource: () => source,
      currentTime: 1,
      destination: {},
    } as unknown as AudioContext
    queue.play(context, new ArrayBuffer(4))
    queue.stop(context)
    expect(source.stop).toHaveBeenCalledOnce()
  })
})
