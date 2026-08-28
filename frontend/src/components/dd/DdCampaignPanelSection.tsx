import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
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
import { useLocale } from "@/i18n"
import { ApiError } from "@/lib/api"
import { useJobsRealtime } from "@/realtime/JobsRealtimeProvider"
import { useReportsRealtime } from "@/realtime/ReportsRealtimeProvider"
import { PanelLiveFeedPanel } from "@/components/panel/PanelLiveFeedPanel"

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

function runForCandidate(campaign: DdCampaign, candidateId: string) {
  return campaign.candidate_runs.find((row) => row.candidate_id === candidateId)
}

export function DdCampaignPanelSection({
  campaign,
  onCampaignChange,
}: {
  campaign: DdCampaign
  onCampaignChange: (next: DdCampaign) => void
}) {
  const { t, locale } = useLocale()
  const { jobs } = useJobsRealtime()
  const { reports } = useReportsRealtime()

  const [expertPanels, setExpertPanels] = useState<PopulationSummary[]>([])
  const [panelsLoading, setPanelsLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<string[]>(campaign.selected_candidate_ids)
  const [expertPanelId, setExpertPanelId] = useState<number | null>(campaign.expert_panel_id)
  const [savingSelection, setSavingSelection] = useState(false)
  const [panelStatusByCandidate, setPanelStatusByCandidate] = useState<
    Record<string, PanelSessionStatus | null>
  >({})
  const [runningCandidateId, setRunningCandidateId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reportCreateStarted = useRef<Set<string>>(new Set())

  const selectedPanel = useMemo(
    () => expertPanels.find((panel) => panel.id === expertPanelId) ?? null,
    [expertPanelId, expertPanels],
  )

  useEffect(() => {
    setSelectedIds(campaign.selected_candidate_ids)
    setExpertPanelId(campaign.expert_panel_id)
    reportCreateStarted.current = new Set(
      campaign.candidate_runs.filter((row) => row.report_id).map((row) => row.candidate_id),
    )
  }, [campaign])

  useEffect(() => {
    let cancelled = false
    setPanelsLoading(true)
    void listPopulations({ kind: "expert_panel" })
      .then((rows) => {
        if (!cancelled) setExpertPanels(rows)
      })
      .catch(() => {
        if (!cancelled) setExpertPanels([])
      })
      .finally(() => {
        if (!cancelled) setPanelsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const refreshCampaign = useCallback(async () => {
    const row = await getDdCampaign(campaign.id)
    onCampaignChange(row)
    return row
  }, [campaign.id, onCampaignChange])

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
    setPanelStatusByCandidate((prev) => {
      let changed = false
      const next = { ...prev }
      for (const row of campaign.candidate_runs) {
        if (!row.panel_session_id) continue
        const panelJob = jobs.find(
          (job) =>
            job.kind === "panel_session_run" &&
            job.request?.session_id === row.panel_session_id,
        )
        const panelStatus =
          panelJob?.status === "succeeded"
            ? "succeeded"
            : panelJob?.status === "failed"
              ? "failed"
              : panelJob?.status === "running"
                ? "running"
                : panelJob?.status === "pending"
                  ? "pending"
                  : prev[row.candidate_id] ?? null
        if (panelStatus !== prev[row.candidate_id]) {
          changed = true
          next[row.candidate_id] = panelStatus
        }
      }
      return changed ? next : prev
    })
  }, [jobs, campaign.candidate_runs])

  const persistSelection = useCallback(
    async (nextSelected: string[], nextPanelId: number | null) => {
      setSavingSelection(true)
      setError(null)
      try {
        const row = await updateDdCampaign(campaign.id, {
          selected_candidate_ids: nextSelected,
          expert_panel_id: nextPanelId,
        })
        onCampaignChange(row)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : t("dd.panel.saveSelectionError"))
      } finally {
        setSavingSelection(false)
      }
    },
    [campaign.id, onCampaignChange, t],
  )

  function toggleCandidate(id: string) {
    const next = selectedIds.includes(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id]
    setSelectedIds(next)
    void persistSelection(next, expertPanelId)
  }

  function onExpertPanelChange(value: string) {
    const nextPanelId = value ? Number(value) : null
    if (value && !Number.isFinite(nextPanelId)) return
    setExpertPanelId(nextPanelId)
    void persistSelection(selectedIds, nextPanelId)
  }

  function selectAllCandidates() {
    const next = campaign.candidates.map((c) => c.id)
    setSelectedIds(next)
    void persistSelection(next, expertPanelId)
  }

  function clearCandidates() {
    setSelectedIds([])
    void persistSelection([], expertPanelId)
  }

  const maybeCreateReport = useCallback(
    async (candidateId: string, sessionId: string, candidateName: string) => {
      if (reportCreateStarted.current.has(candidateId)) return
      reportCreateStarted.current.add(candidateId)
      try {
        await createDdReport({
          session_id: sessionId,
          candidate_id: candidateId,
          title: t("dd.panel.reportTitle", { name: candidateName }),
          locale,
        })
        await refreshCampaign()
      } catch (err) {
        reportCreateStarted.current.delete(candidateId)
        setError(err instanceof ApiError ? err.message : t("dd.panel.reportCreateError"))
      }
    },
    [locale, refreshCampaign, t],
  )

  useEffect(() => {
    for (const row of campaign.candidate_runs) {
      if (!row.panel_session_id || row.report_id) continue
      const panelStatus = panelStatusByCandidate[row.candidate_id]
      if (panelStatus !== "succeeded") continue
      const candidate = campaign.candidates.find((c) => c.id === row.candidate_id)
      if (candidate) {
        void maybeCreateReport(row.candidate_id, row.panel_session_id, candidate.namn)
      }
    }
  }, [
    campaign.candidate_runs,
    campaign.candidates,
    maybeCreateReport,
    panelStatusByCandidate,
  ])

  async function onRunPanel(candidate: DdCandidateCompany) {
    if (expertPanelId == null) {
      setError(t("dd.panel.noExpertPanelSelected"))
      return
    }
    setRunningCandidateId(candidate.id)
    setError(null)
    try {
      const session = await createDdPanelSession(campaign.id, {
        campaign_id: campaign.id,
        candidate_id: candidate.id,
      })
      await runPanelSession(session.id)
      await refreshCampaign()
      setPanelStatusByCandidate((prev) => ({ ...prev, [candidate.id]: "pending" }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("dd.panel.runError"))
    } finally {
      setRunningCandidateId(null)
    }
  }

  if (campaign.candidates.length === 0) return null

  return (
    <div className="mt-10 space-y-8">
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-medium">{t("dd.panel.expertPanelTitle")}</h2>
          {savingSelection ? (
            <span className="text-xs text-muted-foreground">{t("dd.panel.savingSelection")}</span>
          ) : null}
        </div>
        <p className="mb-4 text-sm text-muted-foreground">{t("dd.panel.expertPanelIntro")}</p>
        {panelsLoading ? (
          <p className="text-sm text-muted-foreground">{t("dd.panel.panelsLoading")}</p>
        ) : expertPanels.length === 0 ? (
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>{t("dd.panel.panelsEmpty")}</p>
            <Link className="primary" to="/bolag/expertpaneler/new">
              {t("dd.panel.createExpertPanel")}
            </Link>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-[min(100%,280px)] flex-1 flex-col gap-1 text-sm">
              <span className="text-muted-foreground">{t("dd.panel.expertPanelLabel")}</span>
              <select
                className="dsearch"
                value={expertPanelId ?? ""}
                disabled={savingSelection}
                onChange={(e) => onExpertPanelChange(e.target.value)}
              >
                <option value="">{t("dd.panel.expertPanelPlaceholder")}</option>
                {expertPanels.map((panel) => (
                  <option key={panel.id} value={panel.id}>
                    {panel.name} ({panel.size})
                  </option>
                ))}
              </select>
            </label>
            <Link className="text-sm" to="/bolag/expertpaneler">
              {t("dd.panel.manageExpertPanels")}
            </Link>
          </div>
        )}
        {selectedPanel ? (
          <p className="mt-3 text-sm text-muted-foreground">
            {t("dd.panel.expertPanelSelected", {
              name: selectedPanel.name,
              count: selectedPanel.size,
            })}
          </p>
        ) : null}
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-medium">{t("dd.sourcing.candidatesTitle")}</h2>
          <div className="flex flex-wrap gap-2 text-sm">
            <button type="button" disabled={savingSelection} onClick={selectAllCandidates}>
              {t("dd.panel.selectAllCandidates")}
            </button>
            <button type="button" disabled={savingSelection} onClick={clearCandidates}>
              {t("dd.panel.clearCandidates")}
            </button>
          </div>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">{t("dd.panel.candidatesIntro")}</p>
        <div className="grid gap-3">
          {campaign.candidates.map((c) => {
            const selected = selectedIds.includes(c.id)
            const run = runForCandidate(campaign, c.id)
            const reportId = run?.report_id ?? null
            const liveReport = reportId ? reports.find((r) => r.id === reportId) : null
            const reportStatus = liveReport?.status ?? null
            const panelStatus = panelStatusByCandidate[c.id] ?? null
            const isRunningPanel =
              runningCandidateId === c.id ||
              panelStatus === "pending" ||
              panelStatus === "running"
            const panelSessionId = run?.panel_session_id ?? null
            const showLiveFeed =
              selected &&
              panelSessionId != null &&
              (isRunningPanel ||
                panelStatus === "pending" ||
                panelStatus === "running" ||
                panelStatus === "succeeded" ||
                panelStatus === "failed")

            return (
              <CandidatePanelCard
                key={c.id}
                candidate={c}
                selected={selected}
                savingSelection={savingSelection}
                panelStatus={panelStatus}
                reportStatus={reportStatus}
                reportId={reportId}
                isRunningPanel={isRunningPanel}
                panelReady={expertPanelId != null}
                panelSessionId={panelSessionId}
                showLiveFeed={showLiveFeed}
                onToggle={() => toggleCandidate(c.id)}
                onRunPanel={() => void onRunPanel(c)}
                t={t}
              />
            )
          })}
        </div>
      </section>
    </div>
  )
}

function CandidatePanelCard({
  candidate,
  selected,
  savingSelection,
  panelStatus,
  reportStatus,
  reportId,
  isRunningPanel,
  panelReady,
  panelSessionId,
  showLiveFeed,
  onToggle,
  onRunPanel,
  t,
}: {
  candidate: DdCandidateCompany
  selected: boolean
  savingSelection: boolean
  panelStatus: PanelSessionStatus | null
  reportStatus: Report["status"] | null
  reportId: string | null
  isRunningPanel: boolean
  panelReady: boolean
  panelSessionId: string | null
  showLiveFeed: boolean
  onToggle: () => void
  onRunPanel: () => void
  t: ReturnType<typeof useLocale>["t"]
}) {
  const [confirmRerun, setConfirmRerun] = useState(false)

  useEffect(() => {
    if (!selected) setConfirmRerun(false)
  }, [selected])

  function handleRunClick() {
    if (reportId) {
      setConfirmRerun(true)
      return
    }
    onRunPanel()
  }

  return (
    <div className="rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 p-4">
      <div className="flex flex-wrap items-start gap-3">
        <input
          type="checkbox"
          className="mt-1"
          checked={selected}
          disabled={savingSelection}
          aria-label={t("dd.panel.selectCandidate", { name: candidate.namn })}
          onChange={onToggle}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="font-medium">{candidate.namn}</div>
            <div className="text-xs text-muted-foreground">{candidate.organisationsnummer}</div>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">{candidate.beskrivning}</p>
          <dl className="mt-3 grid gap-1 text-sm md:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("dd.sourcing.candidateAge")}
              </dt>
              <dd>{t("dd.sourcing.candidateAgeValue", { years: candidate.alder_ar })}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                {t("dd.sourcing.candidateRegion")}
              </dt>
              <dd>{candidate.omrade}</dd>
            </div>
          </dl>

          {selected ? (
            <div className="mt-4 flex flex-col gap-3 border-t border-[color:var(--border-hairline)] pt-4">
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
                      disabled={isRunningPanel || savingSelection || !panelReady}
                      onClick={() => {
                        setConfirmRerun(false)
                        onRunPanel()
                      }}
                    >
                      {t("dd.panel.rerunConfirmContinue")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    className="primary"
                    disabled={isRunningPanel || savingSelection || !panelReady}
                    onClick={handleRunClick}
                  >
                    {isRunningPanel ? t("dd.panel.runningPanel") : t("dd.panel.runPanel")}
                  </button>
                  {panelStatus ? (
                    <span className={panelStatusClass(panelStatus)}>
                      {t(`dd.panel.panelStatus.${panelStatus}`)}
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
              )}
            </div>
          ) : null}
          {showLiveFeed && panelSessionId ? (
            <PanelLiveFeedPanel sessionId={panelSessionId} enabled={showLiveFeed} />
          ) : null}
        </div>
      </div>
    </div>
  )
}
