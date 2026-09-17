export function smeProductAllowsPath(pathname: string): boolean {
  return pathname === "/jobs" || pathname.startsWith("/jobs/")
}
