/** 24 kHz microphone capture shared by single-expert and group voice. */
export type VoiceCaptureHandle = {
  sampleRate: number
  stop: () => void
}

export async function startVoiceCapture(
  context: AudioContext,
  stream: MediaStream,
  onFrame: (frame: Float32Array, sampleRate: number) => void,
): Promise<VoiceCaptureHandle> {
  await context.audioWorklet.addModule(
    new URL("../../components/chat/pcmCapture.worklet.ts", import.meta.url),
  )
  const source = context.createMediaStreamSource(stream)
  const worklet = new AudioWorkletNode(context, "pcm-capture")
  const silent = context.createGain()
  silent.gain.value = 0
  source.connect(worklet)
  worklet.connect(silent)
  silent.connect(context.destination)
  worklet.port.onmessage = (event: MessageEvent<unknown>) => {
    if (event.data instanceof Float32Array) onFrame(event.data, context.sampleRate)
  }
  return {
    sampleRate: context.sampleRate,
    stop: () => {
      worklet.disconnect()
      source.disconnect()
      silent.disconnect()
    },
  }
}
