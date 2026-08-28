import { useCallback, useEffect, useRef, useState } from "react"
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom"
import {
  getDdCampaign,
  updateDdCampaign,
  type DdCampaign,
  type DdCandidateCompany,
} from "@/api/dd"
import { listPopulations } from "@/api/populations"
import type { PopulationSummary } from "@/data/library-types"
import {
  createDdPanelSession,
  getPanelSession,
  runPanelSession,
  type PanelSessionStatus,
} from "@/api/panel"
import { createDdReport, type Report } from "@/api/reports"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { rememberJobPending } from "@/components/layout/AdminShell"
import { PanelLiveFeedPanel } from "@/components/panel/PanelLiveFeedPanel"
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import {
  assignedPanelId,
  ddRunStatus,
  runForCandidate,
} from "@/lib/dd-runs"
import { cn } from "@/lib/utils"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"

type RunTab = "config" | "results"

function parseTab(raw: string | null): RunTab {
  return raw === "results" ? "results" : "config"
}

function panelStatusClass(status: PanelSessionStatus | null): string {
  if (status === "succeeded") return "job-status succeeded"
  if (status === "failed") return "job-status failed"
  if (status === "running" || status === "pending") return "job-status running"
  return "job-status"
}

function reportStatusClass(status: Report["status"] | null): string {
  if (status === "succeeded") return "job-status succeeded"
  if (status === "failed") return "job-status failed"
  if (status === "running" || status === "pending") return "job-status running"
  return "job-status"
}

export function DdCampaignRunPage() {
  const { t, locale } = useLocale()
  const { id, candidateId } = useParams<{ id: string; candidateId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const campaignId = id ? Number(id) : NaN
  const activeTab = parseTab(searchParams.get("tab"))

  const { jobs } = useJobsRealtime()
  const { reports } = useReportsRealtime()

  const [campaign, setCampaign] = useState<DdCampaign | null>(null)
  const [expertPanels, setExpertPanels] = useState<PopulationSummary[]>([])
  const [panelStatus, setPanelStatus] = useState<PanelSessionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmRerun, setConfirmRerun] = useState(false)
  const reportCreateStarted = useRef(false)
  const defaultedTab = useRef(false)

  const candidate: DdCandidateCompany | null =
    campaign && candidateId
      ? (campaign.candidates.find((row) => row.id === candidateId) ?? null)
      : null
  const run = campaign && candidateId ? runForCandidate(campaign, candidateId) : undefined
  const panelId = campaign && candidateId ? assignedPanelId(campaign, candidateId) : null
  const reportId = run?.report_id ?? null
  const liveReport = reportId ? reports.find((row) => row.id === reportId) : null
  const reportStatus = liveReport?.status ?? null
  const panelSessionId = run?.panel_session_id ?? null

  const jobStatus = jobs.find(
    (job) =>
      job.kind === "panel_session_run" && job.request?.session_id === panelSessionId,
  )?.status
  const livePanelStatus: PanelSessionStatus | null =
    jobStatus === "succeeded"
      ? "succeeded"
      : jobStatus === "failed"
        ? "failed"
        : jobStatus === "running"
          ? "running"
          : jobStatus === "pending"
            ? "pending"
            : panelStatus
  const runStatus = ddRunStatus(livePanelStatus)
  const isRunning =
    starting || livePanelStatus === "pending" || livePanelStatus === "running"
  const showLiveFeed =
    panelSessionId != null &&
    (isRunning || livePanelStatus === "succeeded" || livePanelStatus === "failed")

  function setTab(tab: RunTab) {
    setSearchParams({ tab }, { replace: true })
  }

  const refreshCampaign = useCallback(async () => {
    if (!Number.isFinite(campaignId)) return null
    const row = await getDdCampaign(campaignId)
    setCampaign(row)
    return row
  }, [campaignId])

  useEffect(() => {
    if (!Number.isFinite(campaignId)) return
    let cancelled = false
    setLoading(true)
    void Promise.all([getDdCampaign(campaignId), listPopulations({ kind: "expert_panel" })])
      .then(([row, panels]) => {
        if (cancelled) return
        setCampaign(row)
        setExpertPanels(panels)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("dd.campaigns.detail.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [campaignId, t])

  useEffect(() => {
    if (!panelSessionId) {
      setPanelStatus(null)
      return
    }
    let cancelled = false
    void getPanelSession(panelSessionId)
      .then((session) => {
        if (!cancelled) setPanelStatus(session.status)
      })
      .catch(() => {
        if (!cancelled) setPanelStatus(null)
      })
    return () => {
      cancelled = true
    }
  }, [panelSessionId])

  useEffect(() => {
    if (!campaign || defaultedTab.current) return
    defaultedTab.current = true
    if (searchParams.has("tab")) return
    if (runStatus !== "draft") {
      setSearchParams({ tab: "results" }, { replace: true })
    }
  }, [campaign, runStatus, searchParams, setSearchParams])

  useEffect(() => {
    reportCreateStarted.current = Boolean(run?.report_id)
  }, [run?.report_id])

  useEffect(() => {
    if (!candidate || !panelSessionId || run?.report_id || reportCreateStarted.current) return
    if (livePanelStatus !== "succeeded") return
    reportCreateStarted.current = true
    void createDdReport({
      session_id: panelSessionId,
      candidate_id: candidate.id,
      title: t("dd.panel.reportTitle", { name: candidate.namn }),
      locale,
    })
      .then(() => refreshCampaign())
      .catch((err: unknown) => {
        reportCreateStarted.current = false
        setError(err instanceof ApiError ? err.message : t("dd.panel.reportCreateError"))
      })
  }, [candidate, locale, livePanelStatus, panelSessionId, refreshCampaign, run?.report_id, t])

  async function persistPanel(nextPanelId: number | null) {
    if (!campaign || !candidateId) return
    const next = { ...(campaign.panel_assignments ?? {}) }
    if (nextPanelId == null) delete next[candidateId]
    else next[candidateId] = nextPanelId
    setSaving(true)
    setError(null)
    try {
      const row = await updateDdCampaign(campaign.id, { panel_assignments: next })
      setCampaign(row)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dd.panel.saveSelectionError"))
    } finally {
      setSaving(false)
    }
  }

  async function startRun() {
    if (!campaign || !candidate) return
    if (assignedPanelId(campaign, candidate.id) == null) {
      setError(t("dd.panel.noExpertPanelSelected"))
      return
    }
    setStarting(true)
    setError(null)
    try {
      const session = await createDdPanelSession(campaign.id, {
        campaign_id: campaign.id,
        candidate_id: candidate.id,
      })
      const started = await runPanelSession(session.id)
      rememberJobPending(started.job_id)
      await refreshCampaign()
      setPanelStatus("pending")
      setTab("results")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dd.panel.runError"))
    } finally {
      setStarting(false)
      setConfirmRerun(false)
    }
  }

  if (!Number.isFinite(campaignId) || !candidateId) {
    return <Navigate to="/bolag/campaigns" replace />
  }

  if (loading) {
    return (
      <NestedBolagPage>
        <div className="wrap">
          <div className="no-match">{t("dd.campaigns.detail.loading")}</div>
        </div>
      </NestedBolagPage>
    )
  }

  if (!campaign) {
    return <Navigate to="/bolag/campaigns" replace />
  }

  if (!candidate) {
    return (
      <NestedBolagPage>
        <div className="wrap">
          <div className="crumb">
            <Link to={`/bolag/campaigns/${campaign.id}?tab=run`}>{t("dd.panel.runDetailBack")}</Link>
          </div>
          <div className="no-match">{t("dd.panel.runMissingCandidate")}</div>
        </div>
      </NestedBolagPage>
    )
  }

  return (
    <NestedBolagPage>
      <div className="wrap">
        {activeTab === "results" ? (
          <div className="results-nav">
            <Link to={`/bolag/campaigns/${campaign.id}?tab=run`}>{t("dd.panel.runDetailBack")}</Link>
            <Link to={`/bolag/campaigns/${campaign.id}/runs/${candidate.id}?tab=config`}>
              {t("dd.panel.runConfiguration")}
            </Link>
          </div>
        ) : (
          <div className="crumb">
            <Link to={`/bolag/campaigns/${campaign.id}?tab=run`}>{t("dd.panel.runDetailBack")}</Link>
          </div>
        )}

        {activeTab === "config" ? (
          <div className="head-row">
            <div>
              <h1>{candidate.namn}</h1>
              <p>{t("dd.panel.runConfigIntro")}</p>
            </div>
          </div>
        ) : null}

        {activeTab === "config" ? (
          <div
            role="tablist"
            aria-label={t("dd.panel.runTablistAria")}
            className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
          >
            {(
              [
                { id: "config" as const, label: t("dd.panel.runTabConfig") },
                { id: "results" as const, label: t("dd.panel.runTabResults") },
              ] as const
            ).map((tab) => {
              const selected = tab.id === activeTab
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`dd-run-tab-${tab.id}`}
                  aria-selected={selected}
                  aria-controls={`dd-run-panel-${tab.id}`}
                  tabIndex={selected ? 0 : -1}
                  className={cn(
                    "-mb-px border-b-2 px-3 py-2 text-sm",
                    selected
                      ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
                      : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
                  )}
                  onClick={() => setTab(tab.id)}
                >
                  {tab.label}
                  {tab.id === "results" && runStatus === "running" ? (
                    <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-db-gold-500 align-middle" />
                  ) : null}
                </button>
              )
            })}
          </div>
        ) : null}

        {error ? (
          <div className="no-match mb-4" style={{ textAlign: "left" }} role="alert">
            {error}
          </div>
        ) : null}

        {activeTab === "config" ? (
          <div id="dd-run-panel-config" role="tabpanel" aria-labelledby="dd-run-tab-config">
            <label className="mb-6 flex max-w-md flex-col gap-1 text-sm">
              <span className="text-muted-foreground">
                {t("dd.panel.candidatePanelLabel", { name: candidate.namn })}
              </span>
              {expertPanels.length === 0 ? (
                <p className="text-muted-foreground">
                  {t("dd.panel.panelsEmpty")}{" "}
                  <Link to="/bolag/expertpaneler/new">{t("dd.panel.createExpertPanel")}</Link>
                </p>
              ) : (
                <select
                  className="dsel"
                  value={panelId ?? ""}
                  disabled={saving || isRunning}
                  onChange={(e) => {
                    const value = e.target.value
                    void persistPanel(value ? Number(value) : null)
                  }}
                >
                  <option value="">{t("dd.panel.expertPanelPlaceholder")}</option>
                  {expertPanels.map((panel) => (
                    <option key={panel.id} value={panel.id}>
                      {panel.name} ({panel.size})
                    </option>
                  ))}
                </select>
              )}
            </label>
            {confirmRerun ? (
              <div className="confirm-row flex flex-col gap-3 text-sm">
                <p>{t("dd.panel.rerunConfirmMessage")}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => setConfirmRerun(false)}>
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="primary"
                    disabled={isRunning || saving || panelId == null}
                    onClick={() => void startRun()}
                  >
                    {t("dd.panel.rerunConfirmContinue")}
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="primary"
                disabled={isRunning || saving || panelId == null}
                onClick={() => {
                  if (reportId) setConfirmRerun(true)
                  else void startRun()
                }}
              >
                {isRunning ? t("dd.panel.runningPanel") : t("dd.panel.runPanel")}
              </button>
            )}
          </div>
        ) : (
          <div id="dd-run-panel-results" role="tabpanel" aria-labelledby="dd-run-tab-results">
            {runStatus === "draft" && !showLiveFeed ? (
              <div className="no-match" style={{ textAlign: "left" }}>
                <p className="font-medium">{t("dd.panel.runEmptyResultsTitle")}</p>
                <p className="mt-2 text-sm text-muted-foreground">{t("dd.panel.runEmptyResultsBody")}</p>
                <button type="button" className="primary mt-4" onClick={() => setTab("config")}>
                  {t("dd.panel.runGoToConfig")}
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  {livePanelStatus ? (
                    <span className={panelStatusClass(livePanelStatus)}>
                      {t(`dd.panel.panelStatus.${livePanelStatus}`)}
                    </span>
                  ) : null}
                  {reportId && (reportStatus === "pending" || reportStatus === "running") ? (
                    <span className={reportStatusClass(reportStatus)}>
                      {t("dd.panel.generatingReport")}
                    </span>
                  ) : null}
                  {reportId && reportStatus === "failed" ? (
                    <span className={reportStatusClass(reportStatus)}>
                      {t("dd.panel.reportFailed")}
                    </span>
                  ) : null}
                  {reportId && reportStatus === "succeeded" ? (
                    <Link className="primary" to={`/bolag/reports/${reportId}`}>
                      {t("dd.panel.openReport")}
                    </Link>
                  ) : null}
                  {reportId && reportStatus == null ? (
                    <span className={reportStatusClass("pending")}>
                      {t("dd.panel.generatingReport")}
                    </span>
                  ) : null}
                </div>
                {showLiveFeed && panelSessionId ? (
                  <PanelLiveFeedPanel sessionId={panelSessionId} enabled={showLiveFeed} />
                ) : null}
              </div>
            )}
          </div>
        )}
      </div>
    </NestedBolagPage>
  )
}
