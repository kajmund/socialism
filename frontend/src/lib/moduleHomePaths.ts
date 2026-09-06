/**
 * Platform URL for each module's home surface.
 * Kept separate from GET /modules — backend owns frontend_entry, not routes.
 */
export const MODULE_HOME_PATHS: Record<string, string> = {
  dd: "/bolag",
  politik: "/",
  expertgranskning: "/expertgranskning",
  rattsunderlag: "/rattsunderlag",
}

const HOME_MODULE_PRIORITY = ["politik", "dd"] as const

/** First available module home. Sidebar is how you switch when several are on. */
export function homePathForModules(modules: readonly string[]): string | null {
  for (const id of HOME_MODULE_PRIORITY) {
    if (modules.includes(id)) return MODULE_HOME_PATHS[id]
  }
  for (const id of modules) {
    const path = MODULE_HOME_PATHS[id]
    if (path) return path
  }
  return null
}
