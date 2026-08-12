function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID()
  }
  return `spin-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** Browser tab session id for Spinndoktor WS hello (history is keyed by report_id). */
export function getSpindoctorSessionId(): string {
  const key = "opinionssimulator.spindoctorSessionId"
  try {
    const existing = localStorage.getItem(key)
    if (existing) return existing
    const created = randomId()
    localStorage.setItem(key, created)
    return created
  } catch {
    return randomId()
  }
}
