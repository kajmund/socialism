import { useEffect, useRef, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import {
  createRun,
  deleteRunResultAttempt,
  getRun,
  listRunPopulations,
  startRun,
  updateRun,
} from "@/api/runs"
import { AdminShell, rememberJobPending } from "@/components/layout/AdminShell"
import { OasisResultsPanel } from "@/components/runs/OasisResultsPanel"
import { RunActionCard } from "@/components/runs/RunActionCard"
import { RunCreateWizard } from "@/components/runs/RunCreateWizard"
import { RunIdentityFields } from "@/components/runs/RunIdentityFields"
import { RunTimelineSection } from "@/components/runs/RunTimelineSection"
import { Card, CardContent } from "@/components/ui/card"
import {
  makeStimulusControlBranch,
  makeTick,
  normalizeTicks,
} from "@/data/runs"
import { validateRunConfig } from "@/data/runValidation"
import type {
  BranchState,
  OasisRunOptions,
  OasisRunResults,
  RunPopulationOption,
  RunStatus,
  Tick,
} from "@/data/runs-types"
import { ApiError } from "@/lib/api"

type RunTab = "config" | "results"

const DEFAULT_OASIS_OPTIONS: OasisRunOptions = {
  platform: "twitter",
  allow_population_create_post: true,
}

function parseTab(raw: string | null): RunTab {
  return raw === "results" ? "results" : "config"
}

export function ConfigureRunPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const runId = id && id !== "new" ? Number(id) : null
  const isNew = !runId
  const isQuickMode = searchParams.get("mode") === "quick"
  const activeTab = parseTab(searchParams.get("tab"))
  const defaultedTabForRun = useRef<number | null>(null)

  const [loading, setLoading] = useState(!!runId)
  const [populations, setPopulations] = useState<RunPopulationOption[]>([])
  const [name, setName] = useState("Ny körning — v1")
  const [startDate, setStartDate] = useState("2026-08-03")
  const [popId, setPopId] = useState<number | null>(null)
  const [popOpen, setPopOpen] = useState(false)
  const [mainTicks, setMainTicks] = useState<Tick[]>([])
  const [branch, setBranch] = useState<BranchState | null>(null)
  const [oasisOptions, setOasisOptions] =
    useState<OasisRunOptions>(DEFAULT_OASIS_OPTIONS)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [pendingAction, setPendingAction] = useState<"save" | "start" | null>(
    null,
  )
  const [runStatus, setRunStatus] = useState<RunStatus>("draft")
  const [results, setResults] = useState<OasisRunResults | null>(null)
  const [deletingAttemptId, setDeletingAttemptId] = useState<string | null>(null)

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2600)
  }

  function setTab(tab: RunTab) {
    // Keep an explicit tab param so clearing the URL can't re-trigger
    // the "default to results" redirect for non-draft runs.
    const next: Record<string, string> = { tab }
    if (isQuickMode) next.mode = "quick"
    setSearchParams(next, { replace: true })
  }

  useEffect(() => {
    let cancelled = false
    listRunPopulations()
      .then((data) => {
        if (cancelled) return
        setPopulations(data)
        setPopId((current) => current ?? data[0]?.id ?? null)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          showToast(err instanceof ApiError ? err.message : "Kunde inte hämta populationer")
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    setLoading(true)
    getRun(runId)
      .then((run) => {
        if (cancelled) return
        setName(run.name)
        setStartDate(run.start_date ?? "2026-08-03")
        setPopId(run.population_id)
        setMainTicks(normalizeTicks(run.main_ticks))
        setBranch(
          run.branch
            ? {
                ...run.branch,
                a: normalizeTicks(run.branch.a),
                b: normalizeTicks(run.branch.b),
              }
            : null,
        )
        setOasisOptions({
          ...DEFAULT_OASIS_OPTIONS,
          ...(run.oasis_options ?? {}),
        })
        setRunStatus(run.status)
        setResults(run.results)
        if (defaultedTabForRun.current !== runId) {
          defaultedTabForRun.current = runId
          const hasExplicitTab = new URLSearchParams(window.location.search).has(
            "tab",
          )
          if (
            !hasExplicitTab &&
            (run.status === "running" ||
              run.status === "done" ||
              run.status === "failed")
          ) {
            setSearchParams({ tab: "results" }, { replace: true })
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          showToast(err instanceof ApiError ? err.message : "Kunde inte hämta körning")
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [runId, setSearchParams])

  // Poll while simulation is running so the results tab updates when the job finishes.
  useEffect(() => {
    if (!runId || runStatus !== "running") return
    let cancelled = false
    let timer: number | undefined

    async function poll() {
      try {
        const run = await getRun(runId!)
        if (cancelled) return
        setRunStatus(run.status)
        setResults(run.results)
        if (run.status === "running") {
          timer = window.setTimeout(poll, 2500)
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, 5000)
      }
    }

    timer = window.setTimeout(poll, 2500)
    return () => {
      cancelled = true
      if (timer != null) window.clearTimeout(timer)
    }
  }, [runId, runStatus])

  const population =
    populations.find((p) => p.id === popId) ??
    populations[0] ?? {
      id: 0,
      name: "Ingen population",
      size: 0,
      initials: [],
    }

  function updateMain(i: number, next: Tick) {
    const arr = [...mainTicks]
    arr[i] = next
    setMainTicks(arr)
  }
  function removeMain(i: number) {
    setMainTicks(mainTicks.filter((_, idx) => idx !== i))
  }
  function moveMain(i: number, dir: number) {
    const j = i + dir
    if (j < 0 || j >= mainTicks.length) return
    const arr = [...mainTicks]
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    setMainTicks(arr)
  }
  function addMain() {
    const tick = makeTick(mainTicks.length + 1)
    setMainTicks([...mainTicks, tick])
    setOpenKey(tick.key)
  }

  function startBranch(i: number) {
    const nextDay = mainTicks[i].day + 1
    setBranch({ afterIndex: i, mode: "ab", a: [makeTick(nextDay)], b: [makeTick(nextDay)] })
  }

  function startStimulusControlBranch(i: number) {
    setBranch(makeStimulusControlBranch(mainTicks, i))
  }

  function updateBranchTick(side: "a" | "b", i: number, next: Tick) {
    setBranch((b) => {
      if (!b) return b
      const arr = [...b[side]]
      arr[i] = next
      return { ...b, [side]: arr }
    })
  }
  function removeBranchTick(side: "a" | "b", i: number) {
    setBranch((b) =>
      b ? { ...b, [side]: b[side].filter((_, idx) => idx !== i) } : b,
    )
  }
  function moveBranchTick(side: "a" | "b", i: number, dir: number) {
    setBranch((b) => {
      if (!b) return b
      const j = i + dir
      if (j < 0 || j >= b[side].length) return b
      const arr = [...b[side]]
      ;[arr[i], arr[j]] = [arr[j], arr[i]]
      return { ...b, [side]: arr }
    })
  }
  function addBranchTick(side: "a" | "b") {
    if (!branch) return
    const lastDay = branch[side].length
      ? branch[side][branch[side].length - 1].day
      : mainTicks[branch.afterIndex].day + 1
    const tick = makeTick(lastDay + 1)
    setBranch({ ...branch, [side]: [...branch[side], tick] })
    setOpenKey(tick.key)
  }

  async function saveDraft(andStart: boolean) {
    if (!popId) {
      showToast("Välj en population först")
      return
    }
    if (andStart) {
      const check = validateRunConfig({
        name,
        populationId: popId,
        populationSize: population.size,
        startDate,
        mainTicks,
        branch,
      })
      if (!check.ok) {
        showToast(check.errors.slice(0, 2).join(" · "))
        return
      }
    }
    setPendingAction(andStart ? "start" : "save")
    setSaving(true)
    try {
      // Do not force status back to draft when starting — that left the UI on
      // "utkast" if /start timed out while the server already set running.
      const payload = andStart
        ? {
            name,
            population_id: popId,
            start_date: startDate,
            main_ticks: mainTicks,
            branch,
            oasis_options: oasisOptions,
          }
        : {
            name,
            population_id: popId,
            start_date: startDate,
            status: "draft" as const,
            main_ticks: mainTicks,
            branch,
            oasis_options: oasisOptions,
          }
      const saved = runId
        ? await updateRun(runId, payload)
        : await createRun({
            name,
            population_id: popId,
            start_date: startDate,
            status: "draft",
            main_ticks: mainTicks,
            branch,
            oasis_options: oasisOptions,
          })
      if (andStart) {
        setRunStatus("running")
        if (runId) {
          setTab("results")
        }
        const started = await startRun(saved.id)
        setRunStatus(started.status)
        setResults(started.results)
        if (started.job_id) rememberJobPending(started.job_id)
        showToast(`Körning "${name}" startad i bakgrunden`)
        if (!runId) {
          navigate(`/runs/${started.id}/edit?tab=results`, { replace: true })
        }
        return
      }
      setRunStatus(saved.status)
      showToast(`Sparade "${name}" som utkast`)
      window.setTimeout(() => navigate(`/runs/${saved.id}/edit`), 700)
    } catch (err) {
      // If start timed out, the run may already be running — refresh truth from API.
      if (andStart && runId) {
        try {
          const fresh = await getRun(runId)
          setRunStatus(fresh.status)
          setResults(fresh.results)
          if (fresh.status === "running" || fresh.status === "done") {
            showToast(
              fresh.status === "running"
                ? `Körning "${name}" pågår i bakgrunden`
                : `Körning "${name}" är klar`,
            )
            navigate(`/runs/${runId}/edit?tab=results`, { replace: true })
            return
          }
        } catch {
          // fall through to error toast
        }
      }
      showToast(err instanceof ApiError ? err.message : "Kunde inte spara")
    } finally {
      setPendingAction(null)
      setSaving(false)
    }
  }

  async function handleDeleteAttempt(attemptId: string) {
    if (!runId) return
    setDeletingAttemptId(attemptId)
    try {
      const updated = await deleteRunResultAttempt(runId, attemptId)
      setResults(updated.results)
      setRunStatus(updated.status)
      showToast("Resultatet raderades")
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte radera")
    } finally {
      setDeletingAttemptId(null)
    }
  }

  const activeMain = branch ? mainTicks.slice(0, branch.afterIndex + 1) : mainTicks
  const tickCount =
    mainTicks.length + (branch ? branch.a.length + branch.b.length : 0)
  const variantCount = branch ? 2 : 1
  const configLocked = runStatus === "running" || pendingAction !== null
  const pendingMessage =
    pendingAction === "start" ? "Startar körning…" : "Sparar…"

  const timelineProps = {
    mainTicks,
    branch,
    activeMain,
    population,
    openKey,
    onOpenKeyChange: setOpenKey,
    onUpdateMain: updateMain,
    onRemoveMain: removeMain,
    onMoveMain: moveMain,
    onAddMain: addMain,
    onStartBranch: startBranch,
    onStartStimulusControlBranch: startStimulusControlBranch,
    onClearBranch: () => setBranch(null),
    onUpdateBranchTick: updateBranchTick,
    onRemoveBranchTick: removeBranchTick,
    onMoveBranchTick: moveBranchTick,
    onAddBranchTick: addBranchTick,
    disabled: configLocked,
  }

  const wizardProps = {
    name,
    onNameChange: setName,
    startDate,
    onStartDateChange: setStartDate,
    populations,
    popId,
    onPopIdChange: setPopId,
    popOpen,
    onPopOpenChange: setPopOpen,
    ...timelineProps,
    oasisOptions,
    onOasisOptionsChange: setOasisOptions,
    tickCount,
    variantCount,
    runStatus,
    saving,
    pendingAction,
    onSave: () => void saveDraft(false),
    onStart: () => void saveDraft(true),
    onValidationError: showToast,
  }

  if (loading) {
    return (
      <AdminShell>
        <div className="wrap">
          <div className="no-match">Hämtar körning…</div>
        </div>
      </AdminShell>
    )
  }

  if (isNew && !isQuickMode) {
    return (
      <AdminShell>
        <div className="wrap" style={{ maxWidth: 1180 }}>
          <RunCreateWizard {...wizardProps} />
        </div>
        {toast && (
          <div className="fixed bottom-6 right-6 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
            {toast}
          </div>
        )}
        {pendingAction ? (
          <div
            className="run-pending-overlay"
            role="alertdialog"
            aria-modal="true"
            aria-busy="true"
            aria-label={pendingMessage}
          >
            <div className="run-pending-panel">{pendingMessage}</div>
          </div>
        ) : null}
      </AdminShell>
    )
  }

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 1180 }}>
        <div className={"head-row" + (activeTab === "results" ? " head-row-compact" : "")}>
          <div className="head-row-main">
            <h1>{isNew ? "Ny körning" : name || "Körning"}</h1>
            {isNew || activeTab === "config" ? (
              <p>
                {isNew
                  ? "All konfiguration på en sida — spara när du är klar."
                  : "Konfigurera tidslinjen eller följ simuleringsresultatet när körningen körs i bakgrunden."}
              </p>
            ) : null}
          </div>
          <div className="head-row-aside">
            {(isNew || activeTab === "config") && (
              <RunActionCard
                layout="bar"
                platform={oasisOptions.platform}
                onPlatformChange={(platform) =>
                  setOasisOptions((prev) => ({ ...prev, platform }))
                }
                tickCount={tickCount}
                populationSize={population.size}
                variantCount={variantCount}
                runStatus={runStatus}
                saving={saving}
                pendingAction={pendingAction}
                disabled={configLocked}
                onSave={() => void saveDraft(false)}
                onStart={() => void saveDraft(true)}
              />
            )}
            {isNew ? (
              <Link
                to="/runs/new"
                className="head-row-link text-sm text-db-gold-700 underline-offset-2 hover:underline"
              >
                Guidat skapande →
              </Link>
            ) : null}
          </div>
        </div>

        {!isNew ? (
          <div
            role="tablist"
            aria-label="Körningsvy"
            className="mb-6 flex flex-wrap gap-1 border-b border-[color:var(--border-hairline)]"
          >
            {(
              [
                { id: "config" as const, label: "Konfiguration" },
                { id: "results" as const, label: "Resultat" },
              ] as const
            ).map((tab) => {
              const selected = tab.id === activeTab
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`run-tab-${tab.id}`}
                  aria-selected={selected}
                  aria-controls={`run-panel-${tab.id}`}
                  tabIndex={selected ? 0 : -1}
                  className={
                    selected
                      ? "-mb-px border-b-2 border-db-ink-950 px-3 py-2 text-sm font-medium text-[color:var(--text-body)]"
                      : "-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-[color:var(--text-body)]"
                  }
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

        {(isNew || activeTab === "config") ? (
          <div
            role="tabpanel"
            id="run-panel-config"
            aria-labelledby="run-tab-config"
          >
            <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
              <CardContent className="px-0">
                <div className="id-grid">
                  <RunIdentityFields
                    name={name}
                    onNameChange={setName}
                    startDate={startDate}
                    onStartDateChange={setStartDate}
                    populations={populations}
                    popId={popId}
                    onPopIdChange={setPopId}
                    population={population}
                    popOpen={popOpen}
                    onPopOpenChange={setPopOpen}
                    allowPopulationCreatePost={
                      oasisOptions.allow_population_create_post
                    }
                    onAllowPopulationCreatePostChange={(checked) =>
                      setOasisOptions((prev) => ({
                        ...prev,
                        allow_population_create_post: checked,
                      }))
                    }
                    disabled={configLocked}
                  />
                </div>
              </CardContent>
            </Card>

            <RunTimelineSection {...timelineProps} />
          </div>
        ) : (
          <div
            role="tabpanel"
            id="run-panel-results"
            aria-labelledby="run-tab-results"
          >
            {runStatus === "running" ? (
              <div className="mb-3 flex flex-col gap-1">
                <h2 className="text-base font-semibold text-foreground">
                  Simulering pågår
                </h2>
                <p className="text-sm text-muted-foreground">
                  Körningen körs som bakgrundsjobb
                  {results ? " — tidigare resultat behålls nedan" : ""}. Du kan lämna
                  sidan.{" "}
                  <Link
                    to="/jobs"
                    className="text-db-gold-700 underline-offset-2 hover:underline"
                  >
                    Visa bakgrundsjobb →
                  </Link>
                </p>
              </div>
            ) : null}

            {runStatus === "draft" && !results ? (
              <Card className="mb-9 gap-0 ring-1 ring-border">
                <CardContent className="px-5 py-6">
                  <h2 className="mb-2 text-base font-semibold text-foreground">
                    Inget resultat ännu
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Spara och starta körningen under Konfiguration för att få ett
                    simuleringsresultat.
                  </p>
                  <button
                    type="button"
                    className="mt-4 text-sm text-db-gold-700 underline-offset-2 hover:underline"
                    onClick={() => setTab("config")}
                  >
                    Gå till konfiguration →
                  </button>
                </CardContent>
              </Card>
            ) : null}

            {results ? (
              <OasisResultsPanel
                results={results}
                status={runStatus}
                runId={runId ?? undefined}
                branchMode={branch?.mode ?? null}
                onDeleteAttempt={
                  runId ? (attemptId) => void handleDeleteAttempt(attemptId) : undefined
                }
                deletingAttemptId={deletingAttemptId}
              />
            ) : null}

            {runStatus === "failed" && !results ? (
              <Card className="mb-9 gap-0 ring-1 ring-border">
                <CardContent className="px-5 py-6">
                  <h2 className="mb-2 text-base font-semibold text-foreground">
                    Körningen misslyckades
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Se bakgrundsjobben för feldetaljer, eller starta om från
                    konfigurationen.
                  </p>
                </CardContent>
              </Card>
            ) : null}
          </div>
        )}
      </div>

      {toast && (
        <div className="fixed bottom-6 right-6 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      )}
      {pendingAction ? (
        <div
          className="run-pending-overlay"
          role="alertdialog"
          aria-modal="true"
          aria-busy="true"
          aria-label={pendingMessage}
        >
          <div className="run-pending-panel">{pendingMessage}</div>
        </div>
      ) : null}
    </AdminShell>
  )
}
