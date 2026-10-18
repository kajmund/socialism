import wasm from "onnxruntime-web/ort-wasm-simd-threaded.wasm?url"
import script from "onnxruntime-web/ort-wasm-simd-threaded.mjs?url"

const CONTEXT = 64
const WINDOW = 512
const STATE = 2 * 128

export type SileroModel = {
  probability(window: Float32Array): Promise<number>
  reset(): void
}

/** Silero VAD v5. The ONNX runtime is the speech model; we do not reimplement it. */
export async function loadSileroModel(): Promise<SileroModel> {
  const ort = await import("onnxruntime-web")
  ort.env.wasm.wasmPaths = { wasm, mjs: script }
  ort.env.wasm.numThreads = 1
  const session = await ort.InferenceSession.create(
    `${import.meta.env.BASE_URL}vad/silero_vad.onnx`,
    { executionProviders: ["wasm"] },
  )
  let state = new Float32Array(STATE)
  let context = new Float32Array(CONTEXT)
  return {
    reset() {
      state = new Float32Array(STATE)
      context = new Float32Array(CONTEXT)
    },
    async probability(window) {
      if (window.length !== WINDOW) throw new Error("silero_window")
      const input = new Float32Array(CONTEXT + WINDOW)
      input.set(context, 0)
      input.set(window, CONTEXT)
      const result = await session.run({
        input: new ort.Tensor("float32", input, [1, input.length]),
        state: new ort.Tensor("float32", state, [2, 1, 128]),
        sr: new ort.Tensor("int64", BigInt64Array.from([16_000n]), []),
      })
      const next = result.stateN
      state = new Float32Array(next.data as Float32Array)
      context = input.slice(input.length - CONTEXT)
      return Number((result.output.data as Float32Array)[0])
    },
  }
}
