/** Downlink PCM frames are prefixed with a big-endian generation id. */

export function generationFrame(generation: number, pcm: ArrayBuffer): ArrayBuffer {
  const framed = new ArrayBuffer(4 + pcm.byteLength)
  new DataView(framed).setUint32(0, generation)
  new Uint8Array(framed).set(new Uint8Array(pcm), 4)
  return framed
}

export function splitGenerationFrame(
  payload: ArrayBuffer,
): { generation: number; pcm: ArrayBuffer } | null {
  if (payload.byteLength < 4) return null
  return {
    generation: new DataView(payload).getUint32(0),
    pcm: payload.slice(4),
  }
}
