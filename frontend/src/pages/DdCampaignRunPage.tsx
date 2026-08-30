import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom"
import {
  clearDdCandidateResearch,
  getDdCampaign,
  startDdCandidateResearch,
  updateDdCampaign,
  type DdCampaign,
  type DdCandidateCompany,
} from "@/api/dd"
import type { Job, JobStatus } from "@/api/jobs"
import { listPopulations } from "@/api/populations"
import type { PopulationSummary } from "@/data/library-types"
import {
  createDdPanelSession,
  getPanelSession,
  runPanelSession,
  type PanelSessionStatus,
} from "@/api/panel"
import { createDdReport } from "@/api/reports"
import { DdResearchTab, type ResearchSubTab } from "@/components/dd/DdResearchTab"
import { ReportPage } from "@/pages/ReportPage"
import { NestedBolagPage } from "@/components/layout/BolagShell"
import { rememberJobPending } from "@/components/layout/AdminShell"
import { PanelLiveFeedPanel } from "@/components/panel/PanelLiveFeedPanel"
import { Card, CardContent } from "@/components/ui/card"
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

type RunTab = "config" | "research" | "results"

function parseTab(raw: string | null): RunTab {
  if (raw === "results") return "results"
  if (raw === "research") return "research"
  return "config"
}

function parseResearchSub(raw: string | null): ResearchSubTab {
  return raw === "people" ? "people" : "group"
}

function panelStatusClass(status: PanelSessionStatus | null): string {
  if (status === "succeeded") return "job-status succeeded"
  if (status === "failed") return "job-status failed"
  if (status === "running" || status === "pending") return "job-status running"
  return "job-status"
}

function researchStatusClass(status: JobStatus): string {
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
  const researchSub = parseResearchSub(searchParams.get("sub"))

  const { jobs } = useJobsRealtime()

  const [campaign, setCampaign] = useState<DdCampaign | null>(null)
  const [expertPanels, setExpertPanels] = useState<PopulationSummary[]>([])
  const [panelStatus, setPanelStatus] = useState<PanelSessionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [startingResearch, setStartingResearch] = useState(false)
  const [clearingResearch, setClearingResearch] = useState(false)
  const [selectedPeople, setSelectedPeople] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [confirmRerun, setConfirmRerun] = useState(false)
  const [localReportId, setLocalReportId] = useState<string | null>(null)
  const defaultedTab = useRef(false)
  const refreshedResearchJob = useRef<string | null>(null)
  const { reports } = useReportsRealtime()

  const candidate: DdCandidateCompany | null =
    campaign && candidateId
      ? (campaign.candidates.find((row) => row.id === candidateId) ?? null)
      : null
  const run = campaign && candidateId ? runForCandidate(campaign, candidateId) : undefined
  const panelId = campaign && candidateId ? assignedPanelId(campaign, candidateId) : null
  const panelSessionId = run?.panel_session_id ?? null
  const inferredReportId = reports.find((row) =>
    row.sources.some(
      (src) =>
        src.type === "dd_session" &&
        ((panelSessionId != null && src.session_id === panelSessionId) ||
          src.candidate_id === candidateId),
    ),
  )?.id
  const reportId = run?.report_id ?? localReportId ?? inferredReportId ?? null

  const researchJob = useMemo(() => {
    const byId = run?.research_job_id
      ? jobs.find((job) => job.id === run.research_job_id)
      : undefined
    if (byId) return byId
    const matches = jobs.filter(
      (job) =>
        job.kind === "dd_research" &&
        job.request?.campaign_id === campaignId &&
        job.request?.candidate_id === candidateId,
    )
    return matches.sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0] as Job | undefined
  }, [campaignId, candidateId, jobs, run?.research_job_id])
  const isResearching =
    startingResearch ||
    researchJob?.status === "pending" ||
    researchJob?.status === "running"

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

  function setTab(tab: RunTab, sub?: ResearchSubTab) {
    if (tab === "research") {
      setSearchParams({ tab, sub: sub ?? researchSub }, { replace: true })
      return
    }
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
    if (!candidate || !panelSessionId) return
    if (livePanelStatus !== "succeeded") return
    if (run?.report_id || localReportId) return
    let cancelled = false
    void (async () => {
      try {
        const created = await createDdReport({
          session_id: panelSessionId,
          candidate_id: candidate.id,
          title: t("dd.panel.reportTitle", { name: candidate.namn }),
          locale,
        })
        if (cancelled) return
        setLocalReportId(created.id)
        await refreshCampaign()
      } catch (err: unknown) {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t("dd.panel.reportCreateError"))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [candidate, locale, livePanelStatus, localReportId, panelSessionId, refreshCampaign, run?.report_id, t])

  useEffect(() => {
    if (researchJob == null) return
    if (researchJob.status !== "succeeded" && researchJob.status !== "failed") return
    if (refreshedResearchJob.current === researchJob.id) return
    refreshedResearchJob.current = researchJob.id
    void refreshCampaign()
  }, [researchJob, refreshCampaign])

  const peopleRoster = run?.research?.people ?? []
  const isGroupJob = isResearching && researchJob?.request?.mode !== "people"
  const isContinueJob = Boolean(isGroupJob && researchJob?.request?.continue_group)
  useEffect(() => {
    setSelectedPeople(new Set(peopleRoster.map((person) => person.namn)))
  }, [run?.research?.job_id])

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

  async function startResearch(
    mode: "group" | "people",
    personNames: string[] = [],
    continueGroup = false,
  ) {
    if (!campaign || !candidate) return
    if (mode === "group" && !continueGroup && run?.research != null) {
      setError(t("dd.panel.researchNeedClearGroup"))
      return
    }
    if (mode === "people" && run?.research == null) {
      setError(t("dd.panel.researchPeopleNeedGroup"))
      return
    }
    if (mode === "people" && personNames.length === 0) {
      setError(t("dd.panel.researchPeopleNeedSelection"))
      return
    }
    if (mode === "group" && continueGroup && (run?.research?.pending?.length ?? 0) === 0) {
      setError(t("dd.panel.researchNeedPending"))
      return
    }
    setStartingResearch(true)
    setError(null)
    try {
      const job = await startDdCandidateResearch(campaign.id, candidate.id, {
        mode,
        person_names: personNames,
        continue_group: continueGroup,
      })
      rememberJobPending(job.id)
      refreshedResearchJob.current = null
      await refreshCampaign()
      setTab("research", mode === "people" ? "people" : "group")
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dd.panel.researchError"))
    } finally {
      setStartingResearch(false)
    }
  }

  async function clearResearch() {
    if (!campaign || !candidate) return
    setClearingResearch(true)
    setError(null)
    try {
      await clearDdCandidateResearch(campaign.id, candidate.id)
      setSelectedPeople(new Set())
      await refreshCampaign()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dd.panel.researchClearError"))
    } finally {
      setClearingResearch(false)
    }
  }

  function togglePerson(name: string, checked: boolean) {
    setSelectedPeople((prev) => {
      const next = new Set(prev)
      if (checked) next.add(name)
      else next.delete(name)
      return next
    })
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

  const researchMapped = Boolean(run?.research && run.research.companies.length > 0)

  const tabList = (
    <div
      role="tablist"
      aria-label={t("dd.panel.runTablistAria")}
      className="dd-run-chrome-tabs flex flex-wrap gap-1"
    >
      {(
        [
          { id: "config" as const, label: t("dd.panel.runTabConfig") },
          { id: "research" as const, label: t("dd.panel.runTabResearch") },
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
  )

  return (
    <NestedBolagPage>
      <div className="wrap dd-run-page admin-page">
        <div className="admin-page-chrome">
          <div className="dd-run-chrome">
            <Link to={`/bolag/campaigns/${campaign.id}?tab=run`}>{t("dd.panel.runDetailBack")}</Link>
            {tabList}
            <div className="dd-run-chrome-aside">
              {activeTab === "config" ? (
                confirmRerun ? (
                  <>
                    <button type="button" className="btn-save" onClick={() => setConfirmRerun(false)}>
                      {t("common.cancel")}
                    </button>
                    <button
                      type="button"
                      className="btn-run"
                      disabled={isRunning || saving || panelId == null}
                      onClick={() => void startRun()}
                    >
                      {t("dd.panel.rerunConfirmContinue")}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn-run"
                    disabled={isRunning || saving || panelId == null}
                    onClick={() => {
                      if (reportId) setConfirmRerun(true)
                      else void startRun()
                    }}
                  >
                    {isRunning ? t("dd.panel.runningPanel") : t("dd.panel.runPanel")}
                  </button>
                )
              ) : activeTab === "results" && reportId ? (
                <Link to={`/bolag/reports/${reportId}`} className="btn-save">
                  {t("spinndoctor.viewSpinndoktor")}
                </Link>
              ) : null}
            </div>
          </div>

          {activeTab === "config" && confirmRerun ? (
            <p className="mb-4 text-sm text-muted-foreground">{t("dd.panel.rerunConfirmMessage")}</p>
          ) : null}

          {error ? (
            <div className="no-match mb-4 text-left" role="alert">
              {error}
            </div>
          ) : null}
        </div>

        <div className="admin-page-body">
          {activeTab === "config" ? (
            <div id="dd-run-panel-config" role="tabpanel" aria-labelledby="dd-run-tab-config">
              <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
                <CardContent className="px-0">
                  <div className="id-grid id-grid-3">
                    <div className="id-field">
                      <label htmlFor="dd-run-company">{t("dd.panel.runConfigCompany")}</label>
                      <div id="dd-run-company" className="text-sm">
                        <div className="font-medium">{candidate.namn}</div>
                        <div className="text-muted-foreground">
                          {candidate.organisationsnummer || t("common.emDash")}
                        </div>
                      </div>
                    </div>
                    <div className="id-field">
                      <label htmlFor="dd-run-panel">{t("dd.panel.expertPanelLabel")}</label>
                      {expertPanels.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          {t("dd.panel.panelsEmpty")}{" "}
                          <Link to="/bolag/expertpaneler/new">{t("dd.panel.createExpertPanel")}</Link>
                        </p>
                      ) : (
                        <select
                          id="dd-run-panel"
                          className="dsel w-full"
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
                    </div>
                    <div className="id-field">
                      <label>{t("dd.panel.runConfigResearchSummary")}</label>
                      <p className="mb-3 text-sm text-muted-foreground">
                        {researchMapped
                          ? t("dd.panel.runConfigResearchMapped", {
                              companies: run?.research?.companies.length ?? 0,
                              people: run?.research?.people.length ?? 0,
                            })
                          : t("dd.panel.runConfigResearchNone")}
                      </p>
                      <div className="start-buttons">
                        {researchJob ? (
                          <span className={researchStatusClass(researchJob.status)}>
                            {t(`dd.panel.researchStatus.${researchJob.status}`)}
                          </span>
                        ) : null}
                        <button type="button" className="btn-save" onClick={() => setTab("research")}>
                          {t("dd.panel.researchOpen")}
                        </button>
                      </div>
                      {researchJob?.status === "failed" && researchJob.error ? (
                        <p className="mt-2 text-sm text-muted-foreground" role="alert">
                          {researchJob.error}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : activeTab === "research" ? (
            <DdResearchTab
              dossier={run?.research ?? null}
              subTab={researchSub}
              onSubTab={(sub) => setTab("research", sub)}
              selected={selectedPeople}
              disabled={isResearching}
              clearing={clearingResearch}
              isGroupJob={isGroupJob}
              isContinueJob={isContinueJob}
              researchJob={researchJob}
              companyName={candidate.namn}
              companyOrgnr={candidate.organisationsnummer}
              runCreatedAt={run?.created_at}
              onMapGroup={() => void startResearch("group")}
              onMapMore={() => void startResearch("group", [], true)}
              onClear={() => void clearResearch()}
              onToggle={togglePerson}
              onInvestigate={() => void startResearch("people", [...selectedPeople])}
              onInvestigateAll={() =>
                void startResearch(
                  "people",
                  peopleRoster.map((person) => person.namn),
                )
              }
              t={t}
            />
          ) : (
            <div id="dd-run-panel-results" role="tabpanel" aria-labelledby="dd-run-tab-results">
              {reportId ? (
                <ReportPage reportId={reportId} embedded initialViewMode="report" />
              ) : showLiveFeed && panelSessionId ? (
                <div className="space-y-4">
                  {livePanelStatus ? (
                    <span className={panelStatusClass(livePanelStatus)}>
                      {t(`dd.panel.panelStatus.${livePanelStatus}`)}
                    </span>
                  ) : null}
                  <PanelLiveFeedPanel sessionId={panelSessionId} enabled={showLiveFeed} />
                </div>
              ) : (
                <div className="no-match text-left">
                  <p className="font-medium">{t("dd.panel.runEmptyResultsTitle")}</p>
                  <p className="mt-2 text-sm text-muted-foreground">{t("dd.panel.runEmptyResultsBody")}</p>
                  <button type="button" className="btn-run mt-4" onClick={() => setTab("config")}>
                    {t("dd.panel.runGoToConfig")}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </NestedBolagPage>
  )
}
