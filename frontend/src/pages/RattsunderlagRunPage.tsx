import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import {
  createRattsunderlagSession,
  getRattsunderlagResearch,
  getRattsunderlagSession,
  resultFromJob,
  runRattsunderlagSession,
  updateRattsunderlagSession,
  type ForarbeteRef,
  type LagtextRef,
  type PraxisRef,
  type RattsunderlagResult,
  type RattsunderlagSession,
  type RattsunderlagSessionStatus,
  type SourcingStatus,
} from "@/api/rattsunderlag"
import { AdminShell, rememberJobPending } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { Markdown } from "@/components/ui/markdown"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ReportPage } from "@/pages/ReportPage"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"

const BASE = "/rattsunderlag"

type RunTab = "config" | "results"
type ResultsView = "sources" | "report"
type SourceTab = "law" | "praxis" | "travaux"

function tabButtonClass(selected: boolean): string {
  return cn(
    "-mb-px border-b-2 px-3 py-2 text-sm",
    selected
      ? "border-db-ink-950 font-medium text-[color:var(--text-body)]"
      : "border-transparent text-muted-foreground hover:text-[color:var(--text-body)]",
  )
}

function parseTab(raw: string | null): RunTab {
  return raw === "results" ? "results" : "config"
}

function parseResultsView(raw: string | null, running: boolean, hasReport: boolean): ResultsView {
  if (raw === "sources" || raw === "report") return raw
  if (running || !hasReport) return "sources"
  return "report"
}

function statusLabelKey(status: RattsunderlagSessionStatus): MessageKey {
  switch (status) {
    case "draft":
      return "rattsunderlag.page.status.draft"
    case "pending":
      return "rattsunderlag.page.status.pending"
    case "running":
      return "rattsunderlag.page.status.running"
    case "succeeded":
      return "rattsunderlag.page.status.succeeded"
    case "failed":
      return "rattsunderlag.page.status.failed"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function sourcingKey(status: SourcingStatus): MessageKey {
  switch (status) {
    case "complete":
      return "rattsunderlag.status.complete"
    case "partial":
      return "rattsunderlag.status.partial"
    case "no_sources_found":
      return "rattsunderlag.status.none"
    default: {
      const _exhaustive: never = status
      return _exhaustive
    }
  }
}

function statusTagClass(status: RattsunderlagSessionStatus | null): string {
  switch (status) {
    case "succeeded":
      return "status-tag done"
    case "failed":
      return "status-tag failed"
    case "pending":
    case "running":
      return "status-tag running"
    case "draft":
      return "status-tag draft"
    default:
      return "status-tag"
  }
}

function SourceCard({
  heading,
  body,
  href,
}: {
  heading: string
  body: string
  href?: string | null
}) {
  return (
    <article className="rounded-md border border-[color:var(--border-hairline)] bg-muted/30 p-3">
      <h3 className="text-sm font-medium">{heading}</h3>
      {body ? <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{body}</p> : null}
      {href ? (
        <a className="mt-2 inline-block text-xs underline" href={href} target="_blank" rel="noreferrer">
          {href}
        </a>
      ) : null}
    </article>
  )
}

function LawList({ rows }: { rows: LagtextRef[] }) {
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <SourceCard
          key={row.sfs_id}
          heading={row.rubrik ? `${row.sfs_id} — ${row.rubrik}` : row.sfs_id}
          body={row.utdrag}
          href={row.url}
        />
      ))}
    </div>
  )
}

function PraxisList({ rows }: { rows: PraxisRef[] }) {
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <SourceCard
          key={row.referens}
          heading={row.instans ? `${row.referens} (${row.instans})` : row.referens}
          body={row.utdrag}
          href={row.url}
        />
      ))}
    </div>
  )
}

function TravauxList({ rows }: { rows: ForarbeteRef[] }) {
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <SourceCard
          key={row.referens}
          heading={row.titel ? `${row.referens} — ${row.titel}` : row.referens}
          body={row.utdrag}
          href={row.url}
        />
      ))}
    </div>
  )
}

function SourcesResult({ result, t }: { result: RattsunderlagResult; t: (key: MessageKey) => string }) {
  const [tab, setTab] = useState<SourceTab>("law")
  const emptyLabel =
    tab === "law"
      ? t("rattsunderlag.emptyLaw")
      : tab === "praxis"
        ? t("rattsunderlag.emptyPraxis")
        : t("rattsunderlag.emptyTravaux")
  return (
    <div className="grid gap-4">
      <span className="text-sm">{t(sourcingKey(result.sourcing_status))}</span>
      <div>
        <h2 className="text-sm font-medium">{t("rattsunderlag.assessment")}</h2>
        <Markdown className="mt-2" content={result.sammanfattning} />
      </div>
      <div
        className="flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
        role="tablist"
        aria-label={t("rattsunderlag.sourcesTablistAria")}
      >
        {(
          [
            ["law", "rattsunderlag.tabLaw"],
            ["praxis", "rattsunderlag.tabPraxis"],
            ["travaux", "rattsunderlag.tabTravaux"],
          ] as const
        ).map(([id, key]) => {
          const selected = tab === id
          return (
            <button
              key={id}
              type="button"
              role="tab"
              id={`rattsunderlag-source-tab-${id}`}
              aria-selected={selected}
              aria-controls={`rattsunderlag-source-panel-${id}`}
              tabIndex={selected ? 0 : -1}
              className={tabButtonClass(selected)}
              onClick={() => setTab(id)}
            >
              {t(key)}
            </button>
          )
        })}
      </div>
      <div
        id={`rattsunderlag-source-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`rattsunderlag-source-tab-${tab}`}
      >
        {tab === "law" ? (
          result.lagtext.length ? <LawList rows={result.lagtext} /> : <p className="text-sm text-muted-foreground">{emptyLabel}</p>
        ) : null}
        {tab === "praxis" ? (
          result.praxis.length ? <PraxisList rows={result.praxis} /> : <p className="text-sm text-muted-foreground">{emptyLabel}</p>
        ) : null}
        {tab === "travaux" ? (
          result.forarbeten.length ? (
            <TravauxList rows={result.forarbeten} />
          ) : (
            <p className="text-sm text-muted-foreground">{emptyLabel}</p>
          )
        ) : null}
      </div>
    </div>
  )
}

export function RattsunderlagRunPage() {
  const { t, locale } = useLocale()
  const navigate = useNavigate()
  const { id: routeId } = useParams<{ id?: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const isNew = routeId == null
  const { jobs } = useJobsRealtime()
  const { reports } = useReportsRealtime()

  const activeTab = parseTab(searchParams.get("tab"))
  const [session, setSession] = useState<RattsunderlagSession | null>(null)
  const [title, setTitle] = useState("")
  const [fraga, setFraga] = useState("")
  const [result, setResult] = useState<RattsunderlagResult | null>(null)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmRerun, setConfirmRerun] = useState(false)
  const defaultedTab = useRef(false)

  const sessionId = isNew ? null : (routeId ?? null)
  const sessionStatus = session?.status ?? (isNew ? ("draft" as const) : null)

  const inferredReportId = reports.find((row) =>
    row.sources.some(
      (src) =>
        src.type === "rattsunderlag" &&
        sessionId != null &&
        src.session_id === sessionId,
    ),
  )?.id
  const reportId = session?.report_id ?? inferredReportId ?? null

  const jobStatus = jobs.find(
    (job) =>
      job.kind === "rattsunderlag_research" &&
      (job.request?.session_id === sessionId || job.id === session?.job_id),
  )?.status
  const liveStatus: RattsunderlagSessionStatus | null =
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
  const resultsView = parseResultsView(searchParams.get("view"), isRunning, reportId != null)
  const heading =
    title.trim() ||
    session?.title ||
    (isNew ? t("rattsunderlag.page.newTitle") : t("rattsunderlag.page.title"))

  function setTab(tab: RunTab, opts?: { view?: ResultsView }) {
    if (tab === "results") {
      setSearchParams({ tab, view: opts?.view ?? resultsView }, { replace: true })
      return
    }
    setSearchParams({ tab }, { replace: true })
  }

  useEffect(() => {
    if (isNew || !sessionId) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    getRattsunderlagSession(sessionId)
      .then((row) => {
        if (cancelled) return
        setSession(row)
        setTitle(row.title)
        setFraga(row.fraga)
        setError(null)
        if (row.id !== sessionId) {
          navigate(`${BASE}/${row.id}?${searchParams.toString()}`, { replace: true })
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("rattsunderlag.page.loadError"))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [isNew, navigate, searchParams, sessionId, t])

  useEffect(() => {
    if (isNew || !session || defaultedTab.current) return
    defaultedTab.current = true
    if (searchParams.has("tab")) return
    if (session.status === "draft") return
    if (session.status === "pending" || session.status === "running") {
      setSearchParams({ tab: "results", view: "sources" }, { replace: true })
      return
    }
    setSearchParams(
      { tab: "results", view: reportId ? "report" : "sources" },
      { replace: true },
    )
  }, [isNew, reportId, searchParams, session, setSearchParams])

  useEffect(() => {
    if (activeTab !== "results") return
    const raw = searchParams.get("view")
    if (raw === "sources" || raw === "report") return
    setSearchParams(
      { tab: "results", view: isRunning || !reportId ? "sources" : "report" },
      { replace: true },
    )
  }, [activeTab, isRunning, reportId, searchParams, setSearchParams])

  useEffect(() => {
    if (!sessionId) return
    if (liveStatus !== "succeeded" && liveStatus !== "failed") return
    let cancelled = false
    getRattsunderlagSession(sessionId)
      .then((row) => {
        if (!cancelled) setSession(row)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [liveStatus, sessionId])

  useEffect(() => {
    const jobId = session?.job_id
    if (!jobId) {
      setResult(null)
      return
    }
    if (liveStatus !== "succeeded" && session?.status !== "succeeded") return
    let cancelled = false
    getRattsunderlagResearch(jobId)
      .then((job) => {
        if (!cancelled) setResult(resultFromJob(job))
      })
      .catch(() => {
        if (!cancelled) setResult(null)
      })
    return () => {
      cancelled = true
    }
  }, [liveStatus, session?.job_id, session?.status])

  async function persistSession(): Promise<RattsunderlagSession> {
    const body = {
      title: title.trim(),
      fraga: fraga.trim(),
      locale: locale === "en" ? ("en" as const) : ("sv" as const),
    }
    if (isNew || !sessionId) {
      return createRattsunderlagSession(body)
    }
    return updateRattsunderlagSession(sessionId, body)
  }

  async function saveDraft() {
    setSaving(true)
    setError(null)
    try {
      const saved = await persistSession()
      setSession(saved)
      setTitle(saved.title)
      setFraga(saved.fraga)
      if (isNew) {
        navigate(`${BASE}/${saved.id}?tab=config`, { replace: true })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("rattsunderlag.page.saveError"))
    } finally {
      setSaving(false)
    }
  }

  async function startRun() {
    if (!fraga.trim()) {
      setError(t("rattsunderlag.missingQuestion"))
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
      const started = await runRattsunderlagSession(saved.id)
      rememberJobPending(started.job_id)
      setSession({
        ...saved,
        status: "pending",
        job_id: started.job_id,
        report_id: null,
        underlag_id: null,
      })
      setResult(null)
      navigate(`${BASE}/${saved.id}?tab=results&view=sources`, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("rattsunderlag.page.runError"))
    } finally {
      setStarting(false)
    }
  }

  const chromeTabs = useMemo(
    () => [
      { id: "config" as const, label: t("rattsunderlag.page.configTab") },
      { id: "results" as const, label: t("rattsunderlag.page.resultsTab") },
    ],
    [t],
  )
  const resultTabs = useMemo(
    () => [
      { id: "sources" as const, label: t("rattsunderlag.page.sourcesTab") },
      { id: "report" as const, label: t("rattsunderlag.page.reportTab") },
    ],
    [t],
  )

  if (loading) {
    return (
      <AdminShell>
        <div className="no-match">{t("rattsunderlag.page.loading")}</div>
      </AdminShell>
    )
  }

  return (
    <AdminShell>
      <div className="wrap dd-run-page admin-page">
        <div className="admin-page-chrome">
          <div className="dd-run-chrome">
            <div>
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="kicker" style={{ margin: 0 }}>
                  {t("modules.rattsunderlag.name")}
                </span>
                {liveStatus ? (
                  <span className={statusTagClass(liveStatus)}>{t(statusLabelKey(liveStatus))}</span>
                ) : null}
              </div>
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
              <Link to={BASE} className="btn-save">
                {t("rattsunderlag.page.backToList")}
              </Link>
              {reportId ? (
                <Link to={`/reports/${reportId}`} className="btn-save">
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
                      disabled={isRunning || saving}
                      onClick={() => void startRun()}
                    >
                      {t("rattsunderlag.page.confirmRerun")}
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
                      {saving ? t("rattsunderlag.page.saving") : t("rattsunderlag.page.saveDraft")}
                    </button>
                    <button
                      type="button"
                      className="btn-run"
                      disabled={isRunning || saving}
                      onClick={() => void startRun()}
                    >
                      {isRunning
                        ? t("rattsunderlag.page.running")
                        : liveStatus === "succeeded"
                          ? t("rattsunderlag.page.rerun")
                          : t("rattsunderlag.page.run")}
                    </button>
                  </>
                )
              ) : null}
            </div>
          </div>
          <p className="mb-4 text-sm text-muted-foreground">
            {activeTab === "config"
              ? t("rattsunderlag.page.intro")
              : t("rattsunderlag.page.resultsIntro")}
          </p>
          {error ? (
            <div className="no-match mb-4 text-left" role="alert">
              {error}
            </div>
          ) : null}
          {confirmRerun && activeTab === "config" ? (
            <div className="no-match mb-4 text-left" role="status">
              {t("rattsunderlag.page.rerunWarning")}
            </div>
          ) : null}
          <div
            className="dd-run-chrome-tabs mb-4 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
            role="tablist"
            aria-label={t("rattsunderlag.page.tablistAria")}
          >
            {chromeTabs.map((tab) => {
              const selected = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`rattsunderlag-tab-${tab.id}`}
                  aria-selected={selected}
                  aria-controls={`rattsunderlag-panel-${tab.id}`}
                  tabIndex={selected ? 0 : -1}
                  className={tabButtonClass(selected)}
                  onClick={() => setTab(tab.id)}
                >
                  {tab.label}
                  {tab.id === "results" && isRunning ? (
                    <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-db-gold-500 align-middle" />
                  ) : null}
                </button>
              )
            })}
          </div>
        </div>

        <div className="admin-page-body">
          {activeTab === "config" ? (
            <div id="rattsunderlag-panel-config" role="tabpanel" aria-labelledby="rattsunderlag-tab-config">
            <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
              <CardContent className="space-y-5 px-5 py-5">
                <div className="field">
                  <label htmlFor="rattsunderlag-title">{t("rattsunderlag.page.titleLabel")}</label>
                  <input
                    id="rattsunderlag-title"
                    value={title}
                    disabled={!canEdit}
                    placeholder={t("rattsunderlag.page.titlePlaceholder")}
                    onChange={(event) => setTitle(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="rattsunderlag-fraga">{t("rattsunderlag.questionLabel")}</label>
                  <textarea
                    id="rattsunderlag-fraga"
                    className="mt-2 w-full"
                    rows={10}
                    value={fraga}
                    disabled={!canEdit}
                    placeholder={t("rattsunderlag.questionPlaceholder")}
                    onChange={(event) => setFraga(event.target.value)}
                  />
                </div>
              </CardContent>
            </Card>
            </div>
          ) : (
            <div id="rattsunderlag-panel-results" role="tabpanel" aria-labelledby="rattsunderlag-tab-results">
              <div
                className="mb-4 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
                role="tablist"
                aria-label={t("rattsunderlag.page.resultsTablistAria")}
              >
                {resultTabs.map((tab) => {
                  const selected = resultsView === tab.id
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      id={`rattsunderlag-results-tab-${tab.id}`}
                      aria-selected={selected}
                      aria-controls={`rattsunderlag-results-panel-${tab.id}`}
                      tabIndex={selected ? 0 : -1}
                      className={tabButtonClass(selected)}
                      onClick={() => setTab("results", { view: tab.id })}
                    >
                      {tab.label}
                      {tab.id === "sources" && isRunning ? (
                        <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-db-gold-500 align-middle" />
                      ) : null}
                    </button>
                  )
                })}
              </div>
              <div
                id={`rattsunderlag-results-panel-${resultsView}`}
                role="tabpanel"
                aria-labelledby={`rattsunderlag-results-tab-${resultsView}`}
              >
              {resultsView === "sources" ? (
                <div className="space-y-4">
                  {session?.error && liveStatus === "failed" ? (
                    <p className="text-sm text-destructive">{session.error}</p>
                  ) : null}
                  {result ? (
                    <>
                      <SourcesResult result={result} t={t} />
                      {session?.underlag_id ? (
                        <Link className="text-sm underline" to="/expertgranskning/new">
                          {t("rattsunderlag.sendToReview")}
                        </Link>
                      ) : null}
                    </>
                  ) : (
                    <div className="no-match text-left">
                      <p className="font-medium">{t("rattsunderlag.page.emptySourcesTitle")}</p>
                      <p className="mt-2 text-sm text-muted-foreground">
                        {isRunning
                          ? t("rattsunderlag.page.searching")
                          : t("rattsunderlag.page.emptySourcesBody")}
                      </p>
                    </div>
                  )}
                </div>
              ) : reportId ? (
                <ReportPage reportId={reportId} embedded initialViewMode="report" />
              ) : (
                <div className="no-match text-left">
                  <p className="font-medium">{t("rattsunderlag.page.emptyReportTitle")}</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {isRunning
                      ? t("rattsunderlag.page.generatingReport")
                      : t("rattsunderlag.page.emptyReportBody")}
                  </p>
                </div>
              )}
              </div>
            </div>
          )}
        </div>
      </div>
    </AdminShell>
  )
}
