import { describe, expect, it } from "vitest"
import {
  BOLAG_DEMO_CUSTOMER_ID,
  OS_CUSTOMER_ID,
  customerIdForExpertWrite,
  customerScopeFromPathname,
  helpChatTenantForRole,
} from "@/lib/scoping"

describe("customerScopeFromPathname", () => {
  it("treats /bolag routes as the bolag customer", () => {
    expect(customerScopeFromPathname("/bolag/campaigns")).toBe("bolag")
    expect(customerScopeFromPathname("/reports")).toBe("admin")
  })
})

describe("customerIdForExpertWrite", () => {
  it("uses the logged-in kund when the account is bound", () => {
    expect(customerIdForExpertWrite(7)).toBe(7)
  })

  it("falls back to Bolag demo when the account has no kund", () => {
    expect(customerIdForExpertWrite(null)).toBe(BOLAG_DEMO_CUSTOMER_ID)
    expect(customerIdForExpertWrite(undefined)).toBe(BOLAG_DEMO_CUSTOMER_ID)
  })
})

describe("helpChatTenantForRole", () => {
  it("maps bolag to the bolag-demo tenant and dd module", () => {
    expect(helpChatTenantForRole("bolag")).toEqual({
      customer_id: BOLAG_DEMO_CUSTOMER_ID,
      module: "dd",
    })
  })

  it("maps admin and user to Devbrains and politik", () => {
    expect(helpChatTenantForRole("admin")).toEqual({
      customer_id: OS_CUSTOMER_ID,
      module: "politik",
    })
    expect(helpChatTenantForRole("user")).toEqual({
      customer_id: OS_CUSTOMER_ID,
      module: "politik",
    })
  })

  it("returns null when no role is logged in", () => {
    expect(helpChatTenantForRole(null)).toBeNull()
  })
})
