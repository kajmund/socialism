const WINDOW = 512

export type SileroModel = {
  probability(window: Float32Array): Promise<number>
  reset(): void
}

/**
 * Silero VAD v5 runs in sileroModel.worker.ts so the ONNX inference never
 * blocks the main thread. One shared worker session serves the whole page.
 */
let sharedModel: Promise<SileroModel> | null = null

export function loadSileroModel(): Promise<SileroModel> {
  sharedModel ??= createSileroModel().catch((error: unknown) => {
    sharedModel = null
    throw error
  })
  return sharedModel
}

type WorkerResponse =
  | { type: "loaded" }
  | { type: "result"; id: number; value: number }
  | { type: "error"; id: number; message: string }

type Pending = {
  resolve: (value: number) => void
  reject: (reason: Error) => void
}

async function createSileroModel(): Promise<SileroModel> {
  const worker = new Worker(new URL("./sileroModel.worker.ts", import.meta.url), {
    type: "module",
  })
  const pending = new Map<number, Pending>()
  let nextId = 0
  let failed = false
  let resolveLoaded: (() => void) | null = null
  let rejectLoaded: ((reason: Error) => void) | null = null
  const loaded = new Promise<void>((resolve, reject) => {
    resolveLoaded = resolve
    rejectLoaded = reject
  })

  const failAll = (reason: Error): void => {
    for (const entry of pending.values()) entry.reject(reason)
    pending.clear()
  }

  worker.onerror = () => {
    failed = true
    failAll(new Error("silero_worker_failed"))
    rejectLoaded?.(new Error("silero_worker_failed"))
    rejectLoaded = null
    resolveLoaded = null
  }
  worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
    const data = event.data
    if (data.type === "loaded") {
      resolveLoaded?.()
      resolveLoaded = null
      rejectLoaded = null
      return
    }
    if (data.type === "error" && data.id === -1) {
      rejectLoaded?.(new Error(data.message))
      resolveLoaded = null
      rejectLoaded = null
      return
    }
    const entry = pending.get(data.id)
    if (!entry) return
    pending.delete(data.id)
    if (data.type === "error") entry.reject(new Error(data.message))
    else entry.resolve(data.value)
  }

  worker.postMessage({ type: "load" })
  await loaded

  return {
    reset() {
      if (failed) return
      worker.postMessage({ type: "reset" })
    },
    probability(window) {
      if (failed) return Promise.reject(new Error("silero_worker_failed"))
      if (window.length !== WINDOW) return Promise.reject(new Error("silero_window"))
      return new Promise<number>((resolve, reject) => {
        const id = nextId
        nextId += 1
        pending.set(id, { resolve, reject })
        worker.postMessage({ type: "probability", id, window })
      })
    },
  }
}
