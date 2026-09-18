export function smeProductAllowsPath(pathname: string): boolean {
  return pathname === "/profil" || pathname === "/jobs" || pathname.startsWith("/jobs/")
}
