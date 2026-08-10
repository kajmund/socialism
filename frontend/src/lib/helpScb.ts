const STORAGE_KEY = "opinionssimulator.helpUseScb"

export function getHelpUseScb(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    return false
  }
}

export function setHelpUseScb(enabled: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0")
  } catch {
    // ignore storage failures
  }
}
