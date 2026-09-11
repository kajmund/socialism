import type { Kund } from "@/api/kunder"
import type { Role } from "@/lib/auth"
import {
  BOLAG_DEMO_CUSTOMER_SLUG,
  OS_CUSTOMER_SLUG,
  type CustomerScope,
} from "@/lib/scoping"

export function kunderForScope(
  kunder: Kund[],
  role: Role | null,
  scope?: CustomerScope,
): Kund[] {
  if (scope === "bolag" || role === "bolag") {
    return kunder.filter((row) => row.slug === BOLAG_DEMO_CUSTOMER_SLUG)
  }
  if (role === "admin") return kunder
  return kunder.filter((row) => row.slug === OS_CUSTOMER_SLUG)
}

/**
 * Sidenav follows the signed-in account, not the page URL.
 * Jobs/reports still use page scope; admin keeps the module union on /bolag.
 */
export function moduleScopeForNav(
  role: Role | null,
  pageScope: CustomerScope,
): CustomerScope {
  if (role === "admin") return "admin"
  return pageScope
}

export function uniqueModuleIds(kunder: Kund[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const kund of kunder) {
    for (const id of kund.available_modules) {
      if (seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
  }
  return out
}
