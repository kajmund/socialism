import type { SmeMessage } from "@/api/sme"

export const SME_EXPERT_TURN_STATUSES = [
  "accepted",
  "running",
  "succeeded",
  "failed",
] as const

export type SmeExpertTurnStatus = (typeof SME_EXPERT_TURN_STATUSES)[number]

export type SmeExpertTurnLookup = {
  request_id: string
  thread_type: "expert"
  thread_id: string
  status: SmeExpertTurnStatus
  error: string | null
  messages: SmeMessage[]
}

export type SmeTurnRecoveryAction = "wait" | "apply" | "fail" | "resend"

export function smeTurnRecoveryAction(
  turn: SmeExpertTurnLookup | null,
): SmeTurnRecoveryAction {
  if (turn == null) return "resend"
  switch (turn.status) {
    case "accepted":
    case "running":
      return "wait"
    case "succeeded":
      return "apply"
    case "failed":
      return "fail"
    default: {
      const _exhaustive: never = turn.status
      return _exhaustive
    }
  }
}

export function shouldKeepSmeTurnPending(action: SmeTurnRecoveryAction): boolean {
  return action === "wait" || action === "resend"
}
