const URGENT = new Set(["stopp", "nej", "vänta", "stop", "wait", "no"])

/**
 * Urgent words that must stop playback immediately, without waiting for the
 * server's classifier. Kept in sync with the backend's URGENT set.
 */
export function isUrgentBargeIn(text: string): boolean {
  const normalized = text
    .toLocaleLowerCase("sv")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
  if (!normalized) return false
  return normalized.split(" ").some((token) => URGENT.has(token))
}
