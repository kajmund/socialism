import { decodePcm16 } from "@/components/chat/liveVoiceAudio"

/** Queued TTS playback shared by one expert and a group. */
export class PcmQueue {
  private sources = new Set<AudioBufferSourceNode>()
  private next = 0

  play(context: AudioContext, pcm: ArrayBuffer): void {
    const samples = decodePcm16(pcm)
    const buffer = context.createBuffer(1, samples.length, 24_000)
    buffer.getChannelData(0).set(samples)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    source.onended = () => this.sources.delete(source)
    this.sources.add(source)
    const start = Math.max(context.currentTime + 0.01, this.next)
    source.start(start)
    this.next = start + buffer.duration
  }

  stop(context: AudioContext | null): void {
    for (const source of this.sources) {
      try {
        source.stop()
      } catch {
        // Playback may already have ended.
      }
    }
    this.sources.clear()
    this.next = context?.currentTime ?? 0
  }
}
