import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react"
import { Link, Navigate } from "react-router-dom"
import {
  createExpertgranskningSession,
  getExpertgranskningSession,
  runExpertgranskningSession,
  type ExpertgranskningSessionStatus,
} from "@/api/expertgranskning"
import { listPopulations } from "@/api/populations"
import { createExpertgranskningReport } from "@/api/reports"
import { useAuth } from "@/auth/AuthProvider"
import { AdminShell, rememberJobPending } from "@/components/layout/AdminShell"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { PanelLiveFeedPanel } from "@/components/panel/PanelLiveFeedPanel"
import { UnderlagPicker, type UnderlagSelection } from "@/components/underlag/UnderlagPicker"
import { Card, CardContent } from "@/components/ui/card"
import type { PopulationSummary } from "@/data/library-types"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ReportPage } from "@/pages/ReportPage"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"

type ResultsView = "live" | "report"
type ShellComponent = ComponentType<{ children: ReactNode }>

function statusLabelKey(status: ExpertgranskningSessionStatus): MessageKey {
  switch (status) {
    case "draft":
      return "expertgranskning.page.status.draft"
    case "pending":
      return "expertgranskning.page.status.pending"
    case "running":
      return "expertgranskning.page.status.running"
    case "succeeded":
      return "expertgranskning.page.status.succeeded"
    case "failed":
      return "expertgranskning.page.status.failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function statusClass(status: ExpertgranskningSessionStatus | null): string {
  if (status === "succeeded") return "job-status succeeded"
  if (status === "failed") return "job-status failed"
  if (status === "running" || status === "pending") return "job-status running"
  return "job-status"
}

export function ExpertgranskningPage({
  Shell = AdminShell,
  redirectBolag = true,
}: {
  Shell?: ShellComponent
  redirectBolag?: boolean
} = {}) {
  const { t, locale } = useLocale()
  const { role, hasModule } = useAuth()
  const { jobs } = useJobsRealtime()
  const { reports } = useReportsRealtime()

  const [title, setTitle] = useState("")
  const [documentText, setDocumentText] = useState("")
  const [selectedUnderlag, setSelectedUnderlag] = useState<UnderlagSelection | null>(null)
  const [panelId, setPanelId] = useState<number | null>(null)
  const [expertPanels, setExpertPanels] = useState<PopulationSummary[]>([])
  const [loadingPanels, setLoadingPanels] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionStatus, setSessionStatus] = useState<ExpertgranskningSessionStatus | null>(null)
  const [localReportId, setLocalReportId] = useState<string | null>(null)
  const [resultsView, setResultsView] = useState<ResultsView>("live")

  const inferredReportId = reports.find((row) =>
    row.sources.some(
      (src) =>
        src.type === "expertgranskning_session" &&
        sessionId != null &&
        src.session_id === sessionId,
    ),
  )?.id
  const reportId = localReportId ?? inferredReportId ?? null

  const jobStatus = jobs.find(
    (job) => job.kind === "panel_session_run" && job.request?.session_id === sessionId,
  )?.status
  const liveStatus: ExpertgranskningSessionStatus | null =
    jobStatus === "succeeded"
      ? "succeeded"
      : jobStatus === "failed"
        ? "failed"
        : jobStatus === "running"
          ? "running"
          : jobStatus === "pending"
            ? "pending"
            : sessionStatus
  const isRunning =
    starting || liveStatus === "pending" || liveStatus === "running"
  const showLiveFeed =
    sessionId != null &&
    (isRunning || liveStatus === "succeeded" || liveStatus === "failed")

  useEffect(() => {
    let cancelled = false
    setLoadingPanels(true)
    listPopulations({ kind: "expert_panel", module: "expertgranskning" })
      .then((panels) => {
        if (cancelled) return
        setExpertPanels(panels)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("expertgranskning.page.loadPanelsError"))
      })
      .finally(() => {
        if (!cancelled) setLoadingPanels(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (!sessionId) return
    if (liveStatus !== "succeeded" && liveStatus !== "failed") return
    let cancelled = false
    getExpertgranskningSession(sessionId)
      .then((row) => {
        if (!cancelled) setSessionStatus(row.status)
      })
      .catch(() => {
        /* job status is already shown */
      })
    return () => {
      cancelled = true
    }
  }, [liveStatus, sessionId])

  useEffect(() => {
    if (!sessionId) return
    if (liveStatus !== "succeeded") return
    if (reportId) return
    let cancelled = false
    void (async () => {
      try {
        const created = await createExpertgranskningReport({
          session_id: sessionId,
          title: title.trim() || undefined,
          locale,
        })
        if (cancelled) return
        setLocalReportId(created.id)
        setResultsView("report")
      } catch (err: unknown) {
        if (cancelled) return
        setError(
          err instanceof ApiError ? err.message : t("expertgranskning.page.reportCreateError"),
        )
      }
    })()
    return () => {
      cancelled = true
    }
  }, [locale, liveStatus, reportId, sessionId, t, title])

  async function startRun() {
    const text = documentText.trim()
    if (!text) {
      setError(t("expertgranskning.page.missingDocument"))
      return
    }
    if (panelId == null) {
      setError(t("expertgranskning.page.missingPanel"))
      return
    }
    setStarting(true)
    setError(null)
    try {
      const session = await createExpertgranskningSession({
        document_text: text,
        panel_id: panelId,
        title: title.trim() || undefined,
      })
      const started = await runExpertgranskningSession(session.id)
      rememberJobPending(started.job_id)
      setSessionId(session.id)
      setSessionStatus("pending")
      setLocalReportId(null)
      setResultsView("live")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("expertgranskning.page.runError"))
    } finally {
      setStarting(false)
    }
  }

  const canCreatePanel = hasModule("dd")
  const tabs = useMemo(
    () =>
      [
        { id: "live" as const, label: t("expertgranskning.page.liveTab") },
        { id: "report" as const, label: t("expertgranskning.page.reportTab") },
      ],
    [t],
  )

  if (redirectBolag && role === "bolag" && hasModule("dd")) {
    return <Navigate to="/bolag/expertgranskning" replace />
  }

  return (
    <Shell>
      <div className="wrap dd-run-page admin-page">
        <div className="admin-page-chrome">
          <div className="dd-run-chrome">
            <div>
              <span className="kicker">{t("modules.expertgranskning.name")}</span>
              <h1
                style={{
                  font: "var(--text-h1)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                  margin: 0,
                }}
              >
                {t("expertgranskning.page.title")}
              </h1>
            </div>
            <div className="dd-run-chrome-aside">
              {reportId &&
              (role === "bolag" ? hasModule("dd") : hasModule("politik")) ? (
                <Link
                  to={
                    role === "bolag"
                      ? `/bolag/reports/${reportId}`
                      : `/reports/${reportId}`
                  }
                  className="btn-save"
                >
                  {t("spinndoctor.viewSpinndoktor")}
                </Link>
              ) : null}
              <button
                type="button"
                className="btn-run"
                disabled={isRunning || loadingPanels}
                onClick={() => void startRun()}
              >
                {isRunning ? t("expertgranskning.page.running") : t("expertgranskning.page.run")}
              </button>
            </div>
          </div>
          <p className="mb-4 text-sm text-muted-foreground">{t("expertgranskning.page.intro")}</p>
          {error ? (
            <div className="no-match mb-4 text-left" role="alert">
              {error}
            </div>
          ) : null}
        </div>

        <div className="admin-page-body">
          <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
            <CardContent className="space-y-5 px-5 py-5">
              <div className="field">
                <label htmlFor="expertgranskning-title">
                  {t("expertgranskning.page.titleLabel")}
                </label>
                <input
                  id="expertgranskning-title"
                  value={title}
                  disabled={isRunning}
                  placeholder={t("expertgranskning.page.titlePlaceholder")}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="expertgranskning-document">
                  {t("expertgranskning.page.documentLabel")}
                </label>
                <UnderlagPicker
                  module="expertgranskning"
                  value={selectedUnderlag}
                  disabled={isRunning}
                  onChange={(next) => {
                    setSelectedUnderlag(next)
                    if (next?.extractedText) setDocumentText(next.extractedText)
                  }}
                />
                <textarea
                  id="expertgranskning-document"
                  className="mt-2"
                  rows={12}
                  value={documentText}
                  disabled={isRunning}
                  placeholder={t("expertgranskning.page.documentPlaceholder")}
                  onChange={(event) => setDocumentText(event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="expertgranskning-panel">
                  {t("expertgranskning.page.panelLabel")}
                </label>
                {loadingPanels ? (
                  <p className="text-sm text-muted-foreground">{t("expertPanels.list.loading")}</p>
                ) : expertPanels.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {t("expertgranskning.page.panelsEmpty")}{" "}
                    {canCreatePanel ? (
                      <Link to="/bolag/expertpaneler/new?module=expertgranskning">
                        {t("expertgranskning.page.createPanel")}
                      </Link>
                    ) : null}
                  </p>
                ) : (
                  <select
                    id="expertgranskning-panel"
                    className="dsel w-full"
                    value={panelId ?? ""}
                    disabled={isRunning}
                    onChange={(event) => {
                      const value = event.target.value
                      setPanelId(value ? Number(value) : null)
                    }}
                  >
                    <option value="">{t("expertgranskning.page.panelPlaceholder")}</option>
                    {expertPanels.map((panel) => (
                      <option key={panel.id} value={panel.id}>
                        {panel.name} ({panel.size})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="dd-run-chrome-tabs mb-4 flex flex-wrap gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={cn(resultsView === tab.id && "is-active")}
                onClick={() => setResultsView(tab.id)}
              >
                {tab.label}
                {tab.id === "live" && isRunning ? (
                  <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-db-gold-500 align-middle" />
                ) : null}
              </button>
            ))}
          </div>

          {resultsView === "live" ? (
            sessionId ? (
              <div className="space-y-4">
                {liveStatus ? (
                  <span className={statusClass(liveStatus)}>{t(statusLabelKey(liveStatus))}</span>
                ) : null}
                <PanelLiveFeedPanel
                  key={sessionId}
                  sessionId={sessionId}
                  enabled={showLiveFeed}
                />
              </div>
            ) : (
              <div className="no-match text-left">
                <p className="font-medium">{t("expertgranskning.page.emptyLiveTitle")}</p>
                <p className="mt-2 text-sm text-muted-foreground">
                  {t("expertgranskning.page.emptyLiveBody")}
                </p>
              </div>
            )
          ) : reportId ? (
            <ReportPage reportId={reportId} embedded initialViewMode="spinndoctor" />
          ) : (
            <div className="no-match text-left">
              <p className="font-medium">{t("expertgranskning.page.emptyReportTitle")}</p>
              <p className="mt-2 text-sm text-muted-foreground">
                {isRunning
                  ? t("expertgranskning.page.generatingReport")
                  : t("expertgranskning.page.emptyReportBody")}
              </p>
            </div>
          )}
        </div>
      </div>
    </Shell>
  )
}

export function BolagExpertgranskningPage() {
  return <ExpertgranskningPage Shell={NestedBolagPage} redirectBolag={false} />
}
