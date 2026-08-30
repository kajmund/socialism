import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deleteDdCandidateRun, type DdCampaign, type DdCandidateCompany } from "@/api/dd"
import { getPanelSession, type PanelSessionStatus } from "@/api/panel"
import { listPopulations } from "@/api/populations"
import { Card, CardContent } from "@/components/ui/card"
import { ViewToggle, type ListViewMode } from "@/components/ui/view-toggle"
import type { PopulationSummary } from "@/data/library-types"
import { formatLibraryDate } from "@/data/library"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"
import {
  assignedPanelId,
  campaignRunPath,
  ddRunStatus,
  runForCandidate,
  type DdRunStatus,
} from "@/lib/dd-runs"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"

type Translate = (key: MessageKey, params?: TranslateParams) => string

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

function researchLabel(
  campaign: DdCampaign,
  candidateId: string,
  t: Translate,
): string {
  const research = runForCandidate(campaign, candidateId)?.research
  if (!research || research.companies.length === 0) {
    return t("dd.panel.runListResearchNone")
  }
  return t("dd.panel.runListResearchCount", { count: research.companies.length })
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

type RunItemProps = {
  campaign: DdCampaign
  candidate: DdCandidateCompany
  panelName: string
  status: DdRunStatus
  intl: string
  t: Translate
  onDelete: (candidateId: string) => void
}

function RunActions({
  campaign,
  candidate,
  status,
  t,
  confirming,
  onConfirm,
  onCancel,
  onAskDelete,
  canDelete,
}: {
  campaign: DdCampaign
  candidate: DdCandidateCompany
  status: DdRunStatus
  t: Translate
  confirming: boolean
  onConfirm: () => void
  onCancel: () => void
  onAskDelete: () => void
  canDelete: boolean
}) {
  if (confirming) {
    return (
      <>
        <button type="button" onClick={onCancel}>
          {t("common.cancel")}
        </button>
        <button type="button" className="yes" onClick={onConfirm}>
          {t("common.deleteConfirm")}
        </button>
      </>
    )
  }
  return (
    <>
      {status === "draft" ? (
        <Link className="primary full" to={campaignRunPath(campaign.id, candidate.id, "config")}>
          {t("dd.panel.runContinueConfig")}
        </Link>
      ) : (
        <Link className="primary" to={campaignRunPath(campaign.id, candidate.id, "results")}>
          {primaryResultsLabel(status, t)}
        </Link>
      )}
      {status !== "draft" ? (
        <Link to={campaignRunPath(campaign.id, candidate.id, "config")}>
          {t("dd.panel.runConfiguration")}
        </Link>
      ) : null}
      {canDelete ? (
        <button type="button" onClick={onAskDelete}>
          {t("common.delete")}
        </button>
      ) : null}
    </>
  )
}

function RunCard({ campaign, candidate, panelName, status, intl, t, onDelete }: RunItemProps) {
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
              <span>{t("dd.panel.runListOrgnr")}</span>
              <span className="v">{candidate.organisationsnummer || t("common.emDash")}</span>
            </div>
            <div className="row">
              <span>{t("dd.panel.runListResearch")}</span>
              <span className="v">{researchLabel(campaign, candidate.id, t)}</span>
            </div>
            <div className="row">
              <span>{t("dd.panel.runListUpdated")}</span>
              <span className="v">{formatLibraryDate(when, intl)}</span>
            </div>
          </div>
          {confirming ? (
            <div className="confirm-row">
              <RunActions
                campaign={campaign}
                candidate={candidate}
                status={status}
                t={t}
                confirming
                canDelete={canDelete}
                onConfirm={() => onDelete(candidate.id)}
                onCancel={() => setConfirming(false)}
                onAskDelete={() => setConfirming(true)}
              />
            </div>
          ) : (
            <div className="run-actions">
              <RunActions
                campaign={campaign}
                candidate={candidate}
                status={status}
                t={t}
                confirming={false}
                canDelete={canDelete}
                onConfirm={() => onDelete(candidate.id)}
                onCancel={() => setConfirming(false)}
                onAskDelete={() => setConfirming(true)}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function RunListRow({ campaign, candidate, panelName, status, intl, t, onDelete }: RunItemProps) {
  const [confirming, setConfirming] = useState(false)
  const run = runForCandidate(campaign, candidate.id)
  const assigned = campaign.panel_assignments?.[candidate.id] != null
  const canDelete = Boolean(run || assigned)
  const when = run?.updated_at || campaign.updated_at
  return (
    <div className="admin-list-row admin-list-dd-runs">
      <div>
        <div className="nm">{candidate.namn}</div>
        <div className="meta">{candidate.organisationsnummer || t("common.emDash")}</div>
      </div>
      <span className={"status-tag " + status}>{statusLabel(status, t)}</span>
      <div className="cell">{panelName || t("common.emDash")}</div>
      <div className="cell">{researchLabel(campaign, candidate.id, t)}</div>
      <div className="cell">{formatLibraryDate(when, intl)}</div>
      <div className={confirming ? "confirm-row" : "admin-list-actions"}>
        <RunActions
          campaign={campaign}
          candidate={candidate}
          status={status}
          t={t}
          confirming={confirming}
          canDelete={canDelete}
          onConfirm={() => onDelete(candidate.id)}
          onCancel={() => setConfirming(false)}
          onAskDelete={() => setConfirming(true)}
        />
      </div>
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
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState<"all" | DdRunStatus>("all")
  const [view, setView] = useState<ListViewMode>("grid")
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

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2400)
    return () => window.clearTimeout(timer)
  }, [toast])

  function panelName(candidateId: string): string {
    const panelId = assignedPanelId(campaign, candidateId)
    return expertPanels.find((panel) => panel.id === panelId)?.name ?? ""
  }

  function itemStatus(candidateId: string): DdRunStatus {
    return ddRunStatus(
      resolvePanelStatus(campaign, candidateId, panelStatusByCandidate[candidateId] ?? null, jobs),
    )
  }

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    return campaign.candidates.filter((candidate) => {
      const status = itemStatus(candidate.id)
      if (statusFilter !== "all" && status !== statusFilter) return false
      if (!q) return true
      const orgnr = (candidate.organisationsnummer ?? "").toLowerCase()
      return candidate.namn.toLowerCase().includes(q) || orgnr.includes(q)
    })
  }, [campaign, query, statusFilter, panelStatusByCandidate, jobs])

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
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : t("dd.panel.runDeleteError"))
    }
  }

  return (
    <section aria-label={t("dd.panel.runTitle")}>
      <p className="mb-4 text-sm text-muted-foreground">{t("dd.panel.runIntro")}</p>
      {campaign.candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("dd.panel.runEmptyCandidates")}</p>
      ) : (
        <>
          <div className="controls-row">
            <div className="controls-left">
              <input
                className="dsearch"
                placeholder={t("dd.panel.runListSearchPlaceholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <select
                className="dsel"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as "all" | DdRunStatus)}
              >
                <option value="all">{t("dd.panel.runListStatusAll")}</option>
                <option value="done">{t("runs.list.statusDone")}</option>
                <option value="running">{t("runs.list.statusRunning")}</option>
                <option value="draft">{t("runs.list.statusDraft")}</option>
                <option value="failed">{t("runs.list.statusFailed")}</option>
              </select>
            </div>
            <div className="controls-right">
              <ViewToggle value={view} onChange={setView} />
            </div>
          </div>
          {list.length === 0 ? (
            <div className="no-match">{t("dd.panel.runListEmptyFilter")}</div>
          ) : view === "grid" ? (
            <div className="run-grid">
              {list.map((candidate) => (
                <RunCard
                  key={candidate.id}
                  campaign={campaign}
                  candidate={candidate}
                  panelName={panelName(candidate.id)}
                  status={itemStatus(candidate.id)}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                />
              ))}
            </div>
          ) : (
            <div className="admin-list-stack">
              {list.map((candidate) => (
                <RunListRow
                  key={candidate.id}
                  campaign={campaign}
                  candidate={candidate}
                  panelName={panelName(candidate.id)}
                  status={itemStatus(candidate.id)}
                  intl={intl}
                  t={t}
                  onDelete={(id) => void handleDelete(id)}
                />
              ))}
            </div>
          )}
        </>
      )}
      {toast ? <div className="toast">{toast}</div> : null}
    </section>
  )
}
