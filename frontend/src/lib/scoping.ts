/**
 * Phase-1 static tenant scope ids (match backend kund_store seed).
 * Replace with auth session claims when Supabase Auth lands.
 */
export const OS_CUSTOMER_ID = 1
export const BOLAG_DEMO_CUSTOMER_ID = 2
export const OS_DEFAULT_PROJECT_ID = 1
export const OS_CUSTOMER_SLUG = "devbrains"
export const BOLAG_DEMO_CUSTOMER_SLUG = "bolag-demo"

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

/** Tenant filter for jobs/reports WebSocket hello (undefined = admin, all tenants). */
export function realtimeCustomerIdForRole(
  role: string | null,
): number | undefined {
  if (role === "bolag") return BOLAG_DEMO_CUSTOMER_ID
  return undefined
}

export type HelpChatTenant = {
  customer_id: number
  module: "dd" | "politik"
}

/** Help chat tenant from the logged-in role. No silent Devbrains fallback. */
export function helpChatTenantForRole(role: string | null): HelpChatTenant | null {
  if (role == null) return null
  if (role === "bolag") {
    return { customer_id: BOLAG_DEMO_CUSTOMER_ID, module: "dd" }
  }
  return { customer_id: OS_CUSTOMER_ID, module: "politik" }
}
