import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { deleteDdCandidateRun, type DdCampaign, type DdCandidateCompany } from "@/api/dd"
import { getPanelSession, type PanelSessionStatus } from "@/api/panel"
import { listPopulations } from "@/api/populations"
import { Card, CardContent } from "@/components/ui/card"
import type { PopulationSummary } from "@/data/library-types"
import { formatLibraryDate } from "@/data/library"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import {
  assignedPanelId,
  campaignRunPath,
  ddRunStatus,
  runForCandidate,
  type DdRunStatus,
} from "@/lib/dd-runs"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

function statusLabel(status: DdRunStatus, t: Translate): string {
  switch (status) {
    case "done":
      return t("runs.status.done")
    case "running":
      return t("runs.status.running")
    case "draft":
      return t("runs.status.draft")
    case "failed":
      return t("runs.status.failed")
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function primaryResultsLabel(status: DdRunStatus, t: Translate): string {
  switch (status) {
    case "running":
      return t("dd.panel.runSeeStatus")
    case "failed":
      return t("dd.panel.runSeeError")
    default:
      return t("dd.panel.runOpenResults")
  }
}

function resolvePanelStatus(
  campaign: DdCampaign,
  candidateId: string,
  fetched: PanelSessionStatus | null,
  jobs: { kind: string; status: string; request?: Record<string, unknown> | null }[],
): PanelSessionStatus | null {
  const run = runForCandidate(campaign, candidateId)
  if (!run?.panel_session_id) return fetched
  const panelJob = jobs.find(
    (job) =>
      job.kind === "panel_session_run" && job.request?.session_id === run.panel_session_id,
  )
  if (panelJob?.status === "succeeded") return "succeeded"
  if (panelJob?.status === "failed") return "failed"
  if (panelJob?.status === "running") return "running"
  if (panelJob?.status === "pending") return "pending"
  return fetched
}

type RunCardProps = {
  campaign: DdCampaign
  candidate: DdCandidateCompany
  panelName: string
  status: DdRunStatus
  intl: string
  t: Translate
  onDelete: (candidateId: string) => void
}

function RunCard({ campaign, candidate, panelName, status, intl, t, onDelete }: RunCardProps) {
  const [confirming, setConfirming] = useState(false)
  const run = runForCandidate(campaign, candidate.id)
  const assigned = campaign.panel_assignments?.[candidate.id] != null
  const canDelete = Boolean(run || assigned)
  const when = run?.updated_at || campaign.updated_at
  return (
    <div className="run-card">
      <Card className="relative h-full gap-0 rounded-[var(--radius-md)] py-4">
        <span className={"status-tag absolute right-4 top-4 " + status}>{statusLabel(status, t)}</span>
        <CardContent className="run-inner px-4">
          <div className="run-top">
            <div className="run-nm">{candidate.namn}</div>
          </div>
          <div className="run-meta">
            {t("dd.panel.runListPanel")} <b>{panelName || t("common.emDash")}</b>
          </div>
          <div className="run-details">
            <div className="row">
              <span>{t("dd.panel.runListUpdated")}</span>
              <span className="v">{formatLibraryDate(when, intl)}</span>
            </div>
          </div>
          {confirming ? (
            <div className="confirm-row" style={{ marginTop: "auto" }}>
              <button type="button" style={{ flex: 1 }} onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(candidate.id)}
              >
                {t("common.deleteConfirm")}
              </button>
            </div>
          ) : (
            <div className="run-actions">
              {status === "draft" ? (
                <Link
                  className="primary full"
                  to={campaignRunPath(campaign.id, candidate.id, "config")}
                >
                  {t("dd.panel.runContinueConfig")}
                </Link>
              ) : (
                <>
                  <Link
                    className="primary"
                    to={campaignRunPath(campaign.id, candidate.id, "results")}
                  >
                    {primaryResultsLabel(status, t)}
                  </Link>
                  <Link to={campaignRunPath(campaign.id, candidate.id, "config")}>
                    {t("dd.panel.runConfiguration")}
                  </Link>
                </>
              )}
              {canDelete ? (
                <button type="button" onClick={() => setConfirming(true)}>
                  {t("common.delete")}
                </button>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function DdCampaignRunList({
  campaign,
  onCampaignChange,
}: {
  campaign: DdCampaign
  onCampaignChange: (next: DdCampaign) => void
}) {
  const { t, intl } = useLocale()
  const { jobs } = useJobsRealtime()
  const [expertPanels, setExpertPanels] = useState<PopulationSummary[]>([])
  const [panelStatusByCandidate, setPanelStatusByCandidate] = useState<
    Record<string, PanelSessionStatus | null>
  >({})
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void listPopulations({ kind: "expert_panel" })
      .then((rows) => {
        if (!cancelled) setExpertPanels(rows)
      })
      .catch(() => {
        if (!cancelled) setExpertPanels([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const sessionIds = campaign.candidate_runs
      .filter((row) => row.panel_session_id)
      .map((row) => [row.candidate_id, row.panel_session_id as string] as const)
    if (sessionIds.length === 0) {
      setPanelStatusByCandidate({})
      return
    }
    void (async () => {
      const next: Record<string, PanelSessionStatus | null> = {}
      await Promise.all(
        sessionIds.map(async ([candidateId, sessionId]) => {
          try {
            const session = await getPanelSession(sessionId)
            next[candidateId] = session.status
          } catch {
            next[candidateId] = null
          }
        }),
      )
      if (!cancelled) setPanelStatusByCandidate(next)
    })()
    return () => {
      cancelled = true
    }
  }, [campaign.candidate_runs])

  function panelName(candidateId: string): string {
    const panelId = assignedPanelId(campaign, candidateId)
    return expertPanels.find((panel) => panel.id === panelId)?.name ?? ""
  }

  async function handleDelete(candidateId: string) {
    try {
      await deleteDdCandidateRun(campaign.id, candidateId)
      onCampaignChange({
        ...campaign,
        candidate_runs: campaign.candidate_runs.filter((row) => row.candidate_id !== candidateId),
        panel_assignments: Object.fromEntries(
          Object.entries(campaign.panel_assignments ?? {}).filter(([id]) => id !== candidateId),
        ),
      })
      setToast(t("dd.panel.runDeleted"))
      window.setTimeout(() => setToast(null), 2400)
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("dd.panel.runDeleteError"))
      window.setTimeout(() => setToast(null), 2400)
    }
  }

  return (
    <section aria-label={t("dd.panel.runTitle")}>
      <div className="mb-3">
        <h2 className="text-lg font-medium">{t("dd.panel.runTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("dd.panel.runIntro")}</p>
      </div>
      {toast ? (
        <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
          {toast}
        </div>
      ) : null}
      {campaign.candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("dd.panel.runEmptyCandidates")}</p>
      ) : (
        <div className="run-grid">
          {campaign.candidates.map((candidate) => {
            const panelStatus = resolvePanelStatus(
              campaign,
              candidate.id,
              panelStatusByCandidate[candidate.id] ?? null,
              jobs,
            )
            return (
              <RunCard
                key={candidate.id}
                campaign={campaign}
                candidate={candidate}
                panelName={panelName(candidate.id)}
                status={ddRunStatus(panelStatus)}
                intl={intl}
                t={t}
                onDelete={(id) => void handleDelete(id)}
              />
            )
          })}
        </div>
      )}
    </section>
  )
}
