import type { DdCampaign } from "@/api/dd"
import type { PanelSessionStatus } from "@/api/panel"

export type DdRunStatus = "draft" | "running" | "done" | "failed"

export function assignedPanelId(campaign: DdCampaign, candidateId: string): number | null {
  const assigned = campaign.panel_assignments?.[candidateId]
  if (assigned != null) return assigned
  return campaign.expert_panel_id
}

export function runForCandidate(campaign: DdCampaign, candidateId: string) {
  return campaign.candidate_runs.find((row) => row.candidate_id === candidateId)
}

export function ddRunStatus(panelStatus: PanelSessionStatus | null): DdRunStatus {
  switch (panelStatus) {
    case "pending":
    case "running":
      return "running"
    case "failed":
      return "failed"
    case "succeeded":
      return "done"
    case "draft":
    case null:
      return "draft"
    default: {
      const _exhaustive: never = panelStatus
      return _exhaustive
    }
  }
}

export function campaignRunPath(
  campaignId: number,
  candidateId: string,
  tab?: "config" | "research" | "results",
  view?: "live" | "report",
): string {
  const base = `/bolag/campaigns/${campaignId}/runs/${candidateId}`
  if (!tab) return base
  if (tab === "results" && view) return `${base}?tab=${tab}&view=${view}`
  return `${base}?tab=${tab}`
}

export function campaignJobHref(
  campaignId: number | null | undefined,
  candidateId?: string | null,
): string | null {
  if (campaignId == null) return null
  if (candidateId) return campaignRunPath(campaignId, candidateId, "results")
  return `/bolag/campaigns/${campaignId}?tab=run`
}
