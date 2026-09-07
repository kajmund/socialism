import type { ReportMode } from "@/api/reports"
import type { AuthUser } from "@/lib/auth"
import { MODULE_REGISTRY } from "@/modules/moduleRegistry"

export const REPORT_MODULES = ["politik", "dd", "expertgranskning", "rattsunderlag"] as const

export type ReportModuleId = (typeof REPORT_MODULES)[number]

export function isReportModuleId(value: string | null | undefined): value is ReportModuleId {
  if (!value) return false
  const manifest = MODULE_REGISTRY[value]
  return manifest != null && manifest.reportModes.length > 0
}

export function moduleForReport(report: { mode: ReportMode }): ReportModuleId {
  const matches = Object.values(MODULE_REGISTRY).filter((manifest) =>
    manifest.reportModes.includes(report.mode),
  )
  if (matches.length !== 1) {
    throw new Error(`Unknown or ambiguous report mode: ${report.mode}`)
  }
  const id = matches[0].id
  if (!isReportModuleId(id)) {
    throw new Error(`Module ${id} is not a report module`)
  }
  return id
}

export function reportModulesFromIds(ids: readonly string[]): ReportModuleId[] {
  return REPORT_MODULES.filter((id) => ids.includes(id) && id in MODULE_REGISTRY)
}

/** Fallback when kund modules have not loaded yet. Empty `modules` is a legacy session. */
export function reportModulesForUser(user: AuthUser | null | undefined): ReportModuleId[] {
  if (!user) return []
  const declared = reportModulesFromIds(user.modules)
  if (declared.length > 0) return declared
  if (user.role === "bolag") return ["dd"]
  return ["politik", "dd"]
}
