import { describe, expect, it } from "vitest"
import {
  BOLAG_DEMO_CUSTOMER_ID,
  OS_CUSTOMER_ID,
  helpChatTenantForRole,
} from "@/lib/scoping"

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
