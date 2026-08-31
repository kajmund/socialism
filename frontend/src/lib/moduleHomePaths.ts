/**
 * Platform URL for each module's home surface.
 * Kept separate from GET /modules — backend owns frontend_entry, not routes.
 */
export const MODULE_HOME_PATHS: Record<string, string> = {
  dd: "/bolag",
  politik: "/",
}
