/** Read the echo-cancellation setting the browser actually applied. */

export function appliedEchoCancellation(stream: MediaStream): boolean | null {
  const track = stream.getAudioTracks()[0]
  if (!track || typeof track.getSettings !== "function") return null
  const value = track.getSettings().echoCancellation
  if (typeof value !== "boolean") return null
  return value
}
