import { useEffect, useMemo, useRef, useState, type ComponentType, type ReactNode } from "react"
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom"
import {
  createExpertgranskningSession,
  getExpertgranskningSession,
  runExpertgranskningSession,
  updateExpertgranskningSession,
  type ExpertgranskningSession,
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

type ShellComponent = ComponentType<{ children: ReactNode }>
type RunTab = "config" | "results"
type ResultsView = "live" | "report"

function basePath(bolag: boolean): string {
  return bolag ? "/bolag/expertgranskning" : "/expertgranskning"
}

function parseTab(raw: string | null): RunTab {
  return raw === "results" ? "results" : "config"
}

function parseResultsView(raw: string | null, running: boolean, hasReport: boolean): ResultsView {
  if (raw === "live" || raw === "report") return raw
  if (running || !hasReport) return "live"
  return "report"
}

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

function statusClassName(status: ExpertgranskningSessionStatus | null): string {
  if (status === "succeeded") return "job-status succeeded"
  if (status === "failed") return "job-status failed"
  if (status === "running" || status === "pending") return "job-status running"
  return "job-status"
}

function ExpertgranskningRunInner({ bolag }: { bolag: boolean }) {
  const { t, locale } = useLocale()
  const { role, hasModule } = useAuth()
  const navigate = useNavigate()
  const { id: routeId } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const isNew = routeId == null
  const base = basePath(bolag)
  const { jobs } = useJobsRealtime()
  const { reports } = useReportsRealtime()

  const activeTab = parseTab(searchParams.get("tab"))
  const [session, setSession] = useState<ExpertgranskningSession | null>(null)
  const [title, setTitle] = useState("")
  const [documentText, setDocumentText] = useState("")
  const [selectedUnderlag, setSelectedUnderlag] = useState<UnderlagSelection | null>(null)
  const [panelId, setPanelId] = useState<number | null>(null)
  const [expertPanels, setExpertPanels] = useState<PopulationSummary[]>([])
  const [loading, setLoading] = useState(!isNew)
  const [loadingPanels, setLoadingPanels] = useState(true)
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmRerun, setConfirmRerun] = useState(false)
  const [localReportId, setLocalReportId] = useState<string | null>(null)
  const defaultedTab = useRef(false)

  const sessionId = isNew ? null : (routeId ?? null)
  const sessionStatus = session?.status ?? (isNew ? ("draft" as const) : null)

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
  const isRunning = starting || liveStatus === "pending" || liveStatus === "running"
  const canEdit =
    !isRunning &&
    (isNew || liveStatus === "draft" || liveStatus === "failed" || liveStatus === "succeeded")
  const showLiveFeed =
    sessionId != null && (isRunning || liveStatus === "succeeded" || liveStatus === "failed")
  const resultsView = parseResultsView(searchParams.get("view"), isRunning, reportId != null)
  const heading =
    title.trim() ||
    session?.topic ||
    (isNew ? t("expertgranskning.page.newTitle") : t("expertgranskning.page.title"))

  function setTab(tab: RunTab, opts?: { view?: ResultsView }) {
    if (tab === "results") {
      setSearchParams({ tab, view: opts?.view ?? resultsView }, { replace: true })
      return
    }
    setSearchParams({ tab }, { replace: true })
  }

  useEffect(() => {
    let cancelled = false
    setLoadingPanels(true)
    listPopulations({ kind: "expert_panel" })
      .then((panels) => {
        if (!cancelled) setExpertPanels(panels)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("expertgranskning.page.loadPanelsError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingPanels(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  useEffect(() => {
    if (isNew || !sessionId) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    getExpertgranskningSession(sessionId)
      .then((row) => {
        if (cancelled) return
        setSession(row)
        setTitle(row.topic)
        setDocumentText(row.document_text)
        setPanelId(row.panel_id)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("expertgranskning.page.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isNew, sessionId, t])

  useEffect(() => {
    if (isNew || !session || defaultedTab.current) return
    defaultedTab.current = true
    if (searchParams.has("tab")) return
    if (session.status === "draft") return
    if (session.status === "pending" || session.status === "running") {
      setSearchParams({ tab: "results", view: "live" }, { replace: true })
      return
    }
    setSearchParams(
      { tab: "results", view: reportId ? "report" : "live" },
      { replace: true },
    )
  }, [isNew, reportId, searchParams, session, setSearchParams])

  useEffect(() => {
    if (activeTab !== "results") return
    const raw = searchParams.get("view")
    if (raw === "live" || raw === "report") return
    setSearchParams(
      { tab: "results", view: isRunning || !reportId ? "live" : "report" },
      { replace: true },
    )
  }, [activeTab, isRunning, reportId, searchParams, setSearchParams])

  useEffect(() => {
    if (!sessionId) return
    if (liveStatus !== "succeeded" && liveStatus !== "failed") return
    let cancelled = false
    getExpertgranskningSession(sessionId)
      .then((row) => {
        if (!cancelled) setSession(row)
      })
      .catch(() => {})
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
        setSearchParams({ tab: "results", view: "report" }, { replace: true })
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
  }, [locale, liveStatus, reportId, sessionId, setSearchParams, t, title])

  async function persistSession(): Promise<ExpertgranskningSession> {
    if (isNew || !sessionId) {
      return createExpertgranskningSession({
        title: title.trim(),
        document_text: documentText,
        panel_id: panelId ?? undefined,
      })
    }
    return updateExpertgranskningSession(sessionId, {
      title: title.trim(),
      document_text: documentText,
      panel_id: panelId ?? undefined,
      clear_panel: panelId == null,
    })
  }

  async function saveDraft() {
    setSaving(true)
    setError(null)
    try {
      const saved = await persistSession()
      setSession(saved)
      setTitle(saved.topic)
      setDocumentText(saved.document_text)
      setPanelId(saved.panel_id)
      if (isNew) {
        navigate(`${base}/${saved.id}?tab=config`, { replace: true })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("expertgranskning.page.saveError"))
    } finally {
      setSaving(false)
    }
  }

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
    if (liveStatus === "succeeded" && reportId && !confirmRerun) {
      setConfirmRerun(true)
      return
    }
    setStarting(true)
    setError(null)
    setConfirmRerun(false)
    try {
      const saved = await persistSession()
      const started = await runExpertgranskningSession(saved.id)
      rememberJobPending(started.job_id)
      setSession({ ...saved, status: "pending", job_id: started.job_id })
      setLocalReportId(null)
      navigate(`${base}/${saved.id}?tab=results&view=live`, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("expertgranskning.page.runError"))
    } finally {
      setStarting(false)
    }
  }

  const canCreatePanel = hasModule("dd")
  const chromeTabs = useMemo(
    () => [
      { id: "config" as const, label: t("expertgranskning.page.configTab") },
      { id: "results" as const, label: t("expertgranskning.page.resultsTab") },
    ],
    [t],
  )
  const resultTabs = useMemo(
    () => [
      { id: "live" as const, label: t("expertgranskning.page.liveTab") },
      { id: "report" as const, label: t("expertgranskning.page.reportTab") },
    ],
    [t],
  )

  if (!bolag && role === "bolag" && hasModule("dd")) {
    const suffix = isNew ? "/new" : sessionId ? `/${sessionId}` : ""
    const qs = searchParams.toString()
    return <Navigate to={`/bolag/expertgranskning${suffix}${qs ? `?${qs}` : ""}`} replace />
  }

  if (loading) {
    return <div className="no-match">{t("expertgranskning.page.loading")}</div>
  }

  return (
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
              {heading}
            </h1>
          </div>
          <div className="dd-run-chrome-aside">
            <Link to={base} className="btn-save">
              {t("expertgranskning.page.backToList")}
            </Link>
            {reportId && (role === "bolag" ? hasModule("dd") : hasModule("politik")) ? (
              <Link
                to={role === "bolag" ? `/bolag/reports/${reportId}` : `/reports/${reportId}`}
                className="btn-save"
              >
                {t("spinndoctor.viewSpinndoktor")}
              </Link>
            ) : null}
            {activeTab === "config" ? (
              confirmRerun ? (
                <>
                  <button type="button" className="btn-save" onClick={() => setConfirmRerun(false)}>
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="btn-run"
                    disabled={isRunning || saving || loadingPanels}
                    onClick={() => void startRun()}
                  >
                    {t("expertgranskning.page.confirmRerun")}
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn-save"
                    disabled={!canEdit || saving || isRunning}
                    onClick={() => void saveDraft()}
                  >
                    {saving ? t("expertgranskning.page.saving") : t("expertgranskning.page.saveDraft")}
                  </button>
                  <button
                    type="button"
                    className="btn-run"
                    disabled={isRunning || saving || loadingPanels}
                    onClick={() => void startRun()}
                  >
                    {isRunning
                      ? t("expertgranskning.page.running")
                      : liveStatus === "succeeded"
                        ? t("expertgranskning.page.rerun")
                        : t("expertgranskning.page.run")}
                  </button>
                </>
              )
            ) : null}
          </div>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          {activeTab === "config"
            ? t("expertgranskning.page.intro")
            : t("expertgranskning.page.resultsIntro")}
        </p>
        {error ? (
          <div className="no-match mb-4 text-left" role="alert">
            {error}
          </div>
        ) : null}
        {confirmRerun && activeTab === "config" ? (
          <div className="no-match mb-4 text-left" role="status">
            {t("expertgranskning.page.rerunWarning")}
          </div>
        ) : null}
        <div className="dd-run-chrome-tabs mb-4 flex flex-wrap gap-1">
          {chromeTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={cn(activeTab === tab.id && "is-active")}
              onClick={() => setTab(tab.id)}
            >
              {tab.label}
              {tab.id === "results" && isRunning ? (
                <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-db-gold-500 align-middle" />
              ) : null}
            </button>
          ))}
        </div>
      </div>

      <div className="admin-page-body">
        {activeTab === "config" ? (
          <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
            <CardContent className="space-y-5 px-5 py-5">
              <div className="field">
                <label htmlFor="expertgranskning-title">{t("expertgranskning.page.titleLabel")}</label>
                <input
                  id="expertgranskning-title"
                  value={title}
                  disabled={!canEdit}
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
                  listAllModules
                  value={selectedUnderlag}
                  disabled={!canEdit}
                  onChange={(next) => {
                    setSelectedUnderlag(next)
                    if (next?.extractedText) setDocumentText(next.extractedText)
                  }}
                />
                <textarea
                  id="expertgranskning-document"
                  className="mt-2 w-full"
                  rows={12}
                  value={documentText}
                  disabled={!canEdit}
                  placeholder={t("expertgranskning.page.documentPlaceholder")}
                  onChange={(event) => setDocumentText(event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="expertgranskning-panel">{t("expertgranskning.page.panelLabel")}</label>
                {loadingPanels ? (
                  <p className="text-sm text-muted-foreground">{t("expertPanels.list.loading")}</p>
                ) : expertPanels.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {t("expertgranskning.page.panelsEmpty")}{" "}
                    {canCreatePanel ? (
                      <Link to="/bolag/expertpaneler/new">{t("expertgranskning.page.createPanel")}</Link>
                    ) : null}
                  </p>
                ) : (
                  <select
                    id="expertgranskning-panel"
                    className="dsel w-full"
                    value={panelId ?? ""}
                    disabled={!canEdit}
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
        ) : (
          <>
            <div className="dd-run-chrome-tabs mb-4 flex flex-wrap gap-1">
              {resultTabs.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={cn(resultsView === tab.id && "is-active")}
                  onClick={() => setTab("results", { view: tab.id })}
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
                    <span className={statusClassName(liveStatus)}>{t(statusLabelKey(liveStatus))}</span>
                  ) : null}
                  <PanelLiveFeedPanel key={sessionId} sessionId={sessionId} enabled={showLiveFeed} />
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
              <ReportPage reportId={reportId} embedded initialViewMode="report" />
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
          </>
        )}
      </div>
    </div>
  )
}

export function ExpertgranskningRunPage({
  Shell = AdminShell,
  bolag = false,
}: {
  Shell?: ShellComponent
  bolag?: boolean
} = {}) {
  return (
    <Shell>
      <ExpertgranskningRunInner bolag={bolag} />
    </Shell>
  )
}

export function BolagExpertgranskningRunPage() {
  return <ExpertgranskningRunPage Shell={NestedBolagPage} bolag />
}
