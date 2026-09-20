declare const sampleRate: number

declare class AudioWorkletProcessor {
  readonly port: MessagePort
}

declare function registerProcessor(
  name: string,
  processorCtor: typeof AudioWorkletProcessor,
): void

class PcmCaptureProcessor extends AudioWorkletProcessor {
  private readonly chunkSize = Math.max(1, Math.round(sampleRate / 10))
  private pending: number[] = []

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0]
    if (!channel) return true

    for (const sample of channel) {
      this.pending.push(sample)
    }
    while (this.pending.length >= this.chunkSize) {
      const chunk = new Float32Array(this.pending.splice(0, this.chunkSize))
      this.port.postMessage(chunk, [chunk.buffer])
    }
    return true
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor)
