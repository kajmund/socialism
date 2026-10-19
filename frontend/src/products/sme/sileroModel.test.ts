import { afterEach, describe, expect, it, vi } from "vitest"

type FakeEvent = { data: unknown }

class FakeWorker {
  static instances: FakeWorker[] = []
  onmessage: ((event: FakeEvent) => void) | null = null
  onerror: ((event: unknown) => void) | null = null
  posted: Array<Record<string, unknown>> = []

  constructor(_url: URL | string, _options?: WorkerOptions) {
    FakeWorker.instances.push(this)
  }

  postMessage(message: Record<string, unknown>): void {
    this.posted.push(message)
  }

  respond(response: Record<string, unknown>): void {
    this.onmessage?.({ data: response })
  }

  fail(): void {
    this.onerror?.(new Error("boom"))
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
  FakeWorker.instances = []
})

describe("sileroModel worker protocol", () => {
  it("loads the worker and resolves probabilities by id", async () => {
    vi.stubGlobal("Worker", FakeWorker)
    const { loadSileroModel } = await import("./sileroModel")
    const pendingModel = loadSileroModel()
    const worker = FakeWorker.instances[0]
    expect(worker.posted[0]).toEqual({ type: "load" })
    worker.respond({ type: "loaded" })
    const model = await pendingModel

    const result = model.probability(new Float32Array(512))
    expect(worker.posted[1]).toMatchObject({ type: "probability", id: 0 })
    worker.respond({ type: "result", id: 0, value: 0.75 })
    await expect(result).resolves.toBe(0.75)
  })

  it("rejects when the worker answers with an error", async () => {
    vi.stubGlobal("Worker", FakeWorker)
    const { loadSileroModel } = await import("./sileroModel")
    const pendingModel = loadSileroModel()
    const worker = FakeWorker.instances[0]
    worker.respond({ type: "loaded" })
    const model = await pendingModel

    const result = model.probability(new Float32Array(512))
    worker.respond({ type: "error", id: 0, message: "silero_window" })
    await expect(result).rejects.toThrow("silero_window")
  })

  it("rejects the load when the worker reports a load error", async () => {
    vi.stubGlobal("Worker", FakeWorker)
    const { loadSileroModel } = await import("./sileroModel")
    const pendingModel = loadSileroModel()
    const worker = FakeWorker.instances[0]
    worker.respond({ type: "error", id: -1, message: "onnx_failed" })
    await expect(pendingModel).rejects.toThrow("onnx_failed")
  })

  it("rejects the load when the worker itself fails", async () => {
    vi.stubGlobal("Worker", FakeWorker)
    const { loadSileroModel } = await import("./sileroModel")
    const pendingModel = loadSileroModel()
    FakeWorker.instances[0].fail()
    await expect(pendingModel).rejects.toThrow("silero_worker_failed")
  })

  it("validates the window length before posting", async () => {
    vi.stubGlobal("Worker", FakeWorker)
    const { loadSileroModel } = await import("./sileroModel")
    const pendingModel = loadSileroModel()
    const worker = FakeWorker.instances[0]
    worker.respond({ type: "loaded" })
    const model = await pendingModel

    await expect(model.probability(new Float32Array(256))).rejects.toThrow("silero_window")
    expect(worker.posted.filter((message) => message.type === "probability")).toHaveLength(0)
  })

  it("posts a reset without waiting for an answer", async () => {
    vi.stubGlobal("Worker", FakeWorker)
    const { loadSileroModel } = await import("./sileroModel")
    const pendingModel = loadSileroModel()
    const worker = FakeWorker.instances[0]
    worker.respond({ type: "loaded" })
    const model = await pendingModel

    model.reset()
    expect(worker.posted.some((message) => message.type === "reset")).toBe(true)
  })
})
