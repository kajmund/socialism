const URGENT = new Set(["stopp", "nej", "vänta", "stop", "wait", "no"])
const BACKCHANNELS = new Set([
  "mm",
  "mhm",
  "mm hm",
  "mmhm",
  "just det",
  "jajust",
  "ja precis",
  "precis",
  "okej",
  "ok",
  "ja",
  "jaha",
  "aha",
  "hm",
  "hmm",
])

/**
 * Urgent words that must stop playback immediately, without waiting for the
 * server's classifier. Kept in sync with the backend's URGENT set.
 */
export function isUrgentBargeIn(text: string): boolean {
  const tokens = normalizeUtterance(text).split(" ").filter(Boolean)
  return tokens.some((token) => URGENT.has(token))
}

export function isListenerCue(text: string): boolean {
  const normalized = normalizeUtterance(text)
  if (!normalized) return false
  if (BACKCHANNELS.has(normalized)) return true
  const tokens = normalized.split(" ")
  return tokens.every((token) => BACKCHANNELS.has(token) || token === "mm" || token === "okej" || token === "ok")
}

function normalizeUtterance(text: string): string {
  return text
    .toLocaleLowerCase("sv")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
}
