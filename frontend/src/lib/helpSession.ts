const STORAGE_KEY = "opinionssimulator.helpSessionId"

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID()
  }
  return `help-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function getHelpSessionId(): string {
  try {
    const existing = localStorage.getItem(STORAGE_KEY)
    if (existing) return existing
    const created = randomId()
    localStorage.setItem(STORAGE_KEY, created)
    return created
  } catch {
    return randomId()
  }
}

export function resetHelpSessionId(): string {
  const created = randomId()
  try {
    localStorage.setItem(STORAGE_KEY, created)
  } catch {
    // ignore storage failures
  }
  return created
}
