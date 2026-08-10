const STORAGE_KEY = "opinionssimulator.helpGroundPopulation"

export function getHelpGroundPopulation(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1"
  } catch {
    return false
  }
}

export function setHelpGroundPopulation(enabled: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0")
  } catch {
    // ignore storage failures
  }
}
