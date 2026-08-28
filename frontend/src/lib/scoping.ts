/**
 * Phase-1 static tenant scope ids (match backend kund_store seed).
 * Replace with auth session claims when Supabase Auth lands.
 */
export const OS_CUSTOMER_ID = 1
export const BOLAG_DEMO_CUSTOMER_ID = 2
export const OS_DEFAULT_PROJECT_ID = 1

/** Which customer slice a shared list page shows. */
export type CustomerScope = "admin" | "bolag"

export function customerIdForScope(scope: CustomerScope): number | null {
  if (scope === "bolag") return BOLAG_DEMO_CUSTOMER_ID
  return null
}

export function matchesCustomerScope(
  row: { customer_id?: number | null },
  scope: CustomerScope,
): boolean {
  const scopedId = customerIdForScope(scope)
  if (scopedId == null) return true
  return row.customer_id === scopedId
}
