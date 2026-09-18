import { describe, expect, it } from "vitest"
import {
  shouldKeepSmeTurnPending,
  smeTurnRecoveryAction,
  type SmeExpertTurnLookup,
} from "./smeTurnRecovery"

function turn(
  status: SmeExpertTurnLookup["status"],
): SmeExpertTurnLookup {
  return {
    request_id: "req-1",
    thread_type: "expert",
    thread_id: "expert-1",
    status,
    error: status === "failed" ? "Chat error" : null,
    messages: [],
  }
}

describe("smeTurnRecoveryAction", () => {
  it("keeps pending when the turn is still running or missing", () => {
    expect(smeTurnRecoveryAction(turn("accepted"))).toBe("wait")
    expect(smeTurnRecoveryAction(turn("running"))).toBe("wait")
    expect(smeTurnRecoveryAction(null)).toBe("resend")
    expect(shouldKeepSmeTurnPending("wait")).toBe(true)
    expect(shouldKeepSmeTurnPending("resend")).toBe(true)
  })

  it("applies a finished reply and fails a finished error", () => {
    expect(smeTurnRecoveryAction(turn("succeeded"))).toBe("apply")
    expect(smeTurnRecoveryAction(turn("failed"))).toBe("fail")
    expect(shouldKeepSmeTurnPending("apply")).toBe(false)
    expect(shouldKeepSmeTurnPending("fail")).toBe(false)
  })
})
