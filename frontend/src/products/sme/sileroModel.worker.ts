/**
 * Silero VAD v5 ONNX inference in a dedicated worker so the main thread
 * stays free for the UI. The client in sileroModel.ts owns the protocol.
 */
import wasm from "onnxruntime-web/ort-wasm-simd-threaded.wasm?url"
import script from "onnxruntime-web/ort-wasm-simd-threaded.mjs?url"
import type { InferenceSession } from "onnxruntime-web"

const CONTEXT = 64
const WINDOW = 512
const STATE = 2 * 128

type Request =
  | { type: "load" }
  | { type: "probability"; id: number; window: Float32Array }
  | { type: "reset" }

type Response =
  | { type: "loaded" }
  | { type: "result"; id: number; value: number }
  | { type: "error"; id: number; message: string }

let ort: typeof import("onnxruntime-web") | null = null
let session: InferenceSession | null = null
let state = new Float32Array(STATE)
let context = new Float32Array(CONTEXT)

async function load(): Promise<void> {
  const runtime = await import("onnxruntime-web")
  runtime.env.wasm.wasmPaths = { wasm, mjs: script }
  runtime.env.wasm.numThreads = 1
  const created = await runtime.InferenceSession.create(
    `${import.meta.env.BASE_URL}vad/silero_vad.onnx`,
    { executionProviders: ["wasm"] },
  )
  ort = runtime
  session = created
}

async function probability(window: Float32Array): Promise<number> {
  const runtime = ort
  const current = session
  if (runtime === null || current === null) throw new Error("silero_not_loaded")
  if (window.length !== WINDOW) throw new Error("silero_window")
  const input = new Float32Array(CONTEXT + WINDOW)
  input.set(context, 0)
  input.set(window, CONTEXT)
  const result = await current.run({
    input: new runtime.Tensor("float32", input, [1, input.length]),
    state: new runtime.Tensor("float32", state, [2, 1, 128]),
    sr: new runtime.Tensor("int64", BigInt64Array.from([16_000n]), []),
  })
  const next = result.stateN
  state = new Float32Array(next.data as Float32Array)
  context = input.slice(input.length - CONTEXT)
  return Number((result.output.data as Float32Array)[0])
}

async function handle(request: Request): Promise<void> {
  if (request.type === "load") {
    try {
      await load()
      postMessage({ type: "loaded" } satisfies Response)
    } catch (error) {
      postMessage({ type: "error", id: -1, message: errorMessage(error) } satisfies Response)
    }
    return
  }
  if (request.type === "reset") {
    state = new Float32Array(STATE)
    context = new Float32Array(CONTEXT)
    return
  }
  try {
    const value = await probability(request.window)
    postMessage({ type: "result", id: request.id, value } satisfies Response)
  } catch (error) {
    postMessage({ type: "error", id: request.id, message: errorMessage(error) } satisfies Response)
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "silero_error"
}

onmessage = (event: MessageEvent<Request>) => {
  void handle(event.data)
}
