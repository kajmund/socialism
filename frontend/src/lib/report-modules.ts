import type { ReportMode } from "@/api/reports"
import type { AuthUser } from "@/lib/auth"

export const REPORT_MODULES = ["politik", "dd"] as const

export type ReportModuleId = (typeof REPORT_MODULES)[number]

export function isReportModuleId(value: string | null | undefined): value is ReportModuleId {
  return value === "politik" || value === "dd"
}

export function moduleForReport(report: { mode: ReportMode }): ReportModuleId {
  return report.mode === "dd" ? "dd" : "politik"
}

/** Modules whose reports this account may see. Empty `modules` is a legacy session. */
export function reportModulesForUser(user: AuthUser | null | undefined): ReportModuleId[] {
  if (!user) return []
  const declared = REPORT_MODULES.filter((id) => user.modules.includes(id))
  if (declared.length > 0) return declared
  if (user.role === "bolag") return ["dd"]
  return ["politik", "dd"]
}
