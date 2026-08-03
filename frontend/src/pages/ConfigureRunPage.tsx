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
import { TickColumn } from "@/components/runs/TickTimeline"
import { Card, CardContent } from "@/components/ui/card"
import { genSeed, makeTick } from "@/data/runs"
import type {
  BranchState,
  OasisRunResults,
  RunPopulationOption,
  RunStatus,
  Tick,
} from "@/data/runs-types"
import { ApiError } from "@/lib/api"

type RunTab = "config" | "results"

function parseTab(raw: string | null): RunTab {
  return raw === "results" ? "results" : "config"
}

export function ConfigureRunPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const runId = id && id !== "new" ? Number(id) : null
  const activeTab = parseTab(searchParams.get("tab"))
  const defaultedTabForRun = useRef<number | null>(null)

  const [loading, setLoading] = useState(!!runId)
  const [populations, setPopulations] = useState<RunPopulationOption[]>([])
  const [name, setName] = useState("Ny körning — v1")
  const [startDate, setStartDate] = useState("2026-08-03")
  const [seed, setSeed] = useState(genSeed())
  const [popId, setPopId] = useState<number | null>(null)
  const [popOpen, setPopOpen] = useState(false)
  const [mainTicks, setMainTicks] = useState<Tick[]>([
    makeTick(1),
    makeTick(2),
    makeTick(3),
  ])
  const [branch, setBranch] = useState<BranchState | null>(null)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
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
    setSearchParams({ tab }, { replace: true })
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
        setSeed(run.seed)
        setStartDate(run.start_date ?? "2026-08-03")
        setPopId(run.population_id)
        setMainTicks(run.main_ticks.length ? run.main_ticks : [makeTick(1)])
        setBranch(run.branch)
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
    setMainTicks([...mainTicks, makeTick(mainTicks.length + 1)])
  }

  function startBranch(i: number) {
    const nextDay = mainTicks[i].day + 1
    setBranch({ afterIndex: i, a: [makeTick(nextDay)], b: [makeTick(nextDay)] })
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
    setBranch((b) => {
      if (!b) return b
      const lastDay = b[side].length
        ? b[side][b[side].length - 1].day
        : mainTicks[b.afterIndex].day + 1
      return { ...b, [side]: [...b[side], makeTick(lastDay + 1)] }
    })
  }

  async function saveDraft(andStart: boolean) {
    if (!popId) {
      showToast("Välj en population först")
      return
    }
    setSaving(true)
    try {
      // Do not force status back to draft when starting — that left the UI on
      // "utkast" if /start timed out while the server already set running.
      const payload = andStart
        ? {
            name,
            population_id: popId,
            seed,
            start_date: startDate,
            main_ticks: mainTicks,
            branch,
          }
        : {
            name,
            population_id: popId,
            seed,
            start_date: startDate,
            status: "draft" as const,
            main_ticks: mainTicks,
            branch,
          }
      const saved = runId
        ? await updateRun(runId, payload)
        : await createRun({
            name,
            population_id: popId,
            seed,
            start_date: startDate,
            status: "draft",
            main_ticks: mainTicks,
            branch,
          })
      if (andStart) {
        setRunStatus("running")
        const started = await startRun(saved.id)
        setRunStatus(started.status)
        setResults(started.results)
        if (started.job_id) rememberJobPending(started.job_id)
        showToast(`Körning "${name}" startad i bakgrunden`)
        navigate(`/runs/${started.id}/edit?tab=results`, { replace: true })
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
      setSaving(false)
    }
  }

  async function handleDeleteAttempt(attemptId: string) {
    if (!runId) return
    const ok = window.confirm("Radera detta simuleringsresultat?")
    if (!ok) return
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
  const configLocked = runStatus === "running"

  if (loading) {
    return (
      <AdminShell>
        <div className="wrap">
          <div className="no-match">Hämtar körning…</div>
        </div>
      </AdminShell>
    )
  }

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 1180 }}>
        <div className="head-row">
          <div>
            <h1>{name || "Körning"}</h1>
            <p>
              Konfigurera tidslinjen eller följ simuleringsresultatet när körningen
              körs i bakgrunden.
            </p>
          </div>
        </div>

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

        {activeTab === "config" ? (
          <div
            role="tabpanel"
            id="run-panel-config"
            aria-labelledby="run-tab-config"
          >
            <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
              <CardContent className="px-0">
                <div className="id-grid">
                  <div className="id-field">
                    <label>Namn / scenario-id</label>
                    <input
                      value={name}
                      disabled={configLocked}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                  <div className="id-field">
                    <label>Startdatum</label>
                    <input
                      type="date"
                      value={startDate}
                      disabled={configLocked}
                      onChange={(e) => setStartDate(e.target.value)}
                    />
                  </div>
                  <div className="id-field">
                    <label>Seed</label>
                    <div className="seed-row">
                      <input
                        className="mono"
                        value={seed}
                        disabled={configLocked}
                        onChange={(e) => setSeed(e.target.value)}
                      />
                      <button
                        type="button"
                        className="seed-refresh"
                        disabled={configLocked}
                        onClick={() => setSeed(genSeed())}
                        title="Slumpa ny seed"
                      >
                        ⟳
                      </button>
                    </div>
                    <div className="seed-hint">
                      Samma seed + olika budskap = jämförbara resultat.
                    </div>
                  </div>
                  <div className="id-field">
                    <label>Population</label>
                    <div
                      className="pop-mini"
                      onClick={() => {
                        if (!configLocked) setPopOpen(true)
                      }}
                    >
                      <div className="cluster">
                        {population.initials.map((ini) => (
                          <div className="av" key={ini}>
                            {ini}
                          </div>
                        ))}
                      </div>
                      <div className="info">
                        <div className="nm">{population.name}</div>
                        <div className="sub">{population.size} personas</div>
                      </div>
                      <span className="swap">Byt ▾</span>
                      {popOpen && (
                        <>
                          <div
                            className="pop-overlay"
                            onClick={(e) => {
                              e.stopPropagation()
                              setPopOpen(false)
                            }}
                          />
                          <div
                            className="pop-dropdown"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {populations.map((p) => (
                              <div
                                key={p.id}
                                className={
                                  "pop-opt" + (p.id === popId ? " sel" : "")
                                }
                                onClick={() => {
                                  setPopId(p.id)
                                  setPopOpen(false)
                                }}
                              >
                                <div className="av">{p.initials[0]}</div>
                                <div className="nm">{p.name}</div>
                                <div className="sub">{p.size} personas</div>
                              </div>
                            ))}
                            <div className="pop-dropdown-foot">
                              <Link to="/populations">
                                Visa alla populationer →
                              </Link>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="tl-section">
              <span className="tl-kicker">Tick-tidslinje</span>
              <TickColumn
                ticks={activeMain}
                openKey={openKey}
                setOpenKey={setOpenKey}
                updateTick={updateMain}
                removeTick={removeMain}
                moveTick={moveMain}
                addTick={branch || configLocked ? () => undefined : addMain}
                onBranch={startBranch}
                branchable={!branch && !configLocked}
                showAdd={!branch && !configLocked}
              />

              {branch && (
                <>
                  <div className="fork-wrap">
                    <div className="fork-line" />
                    <div className="fork-bar">
                      <span className="t">
                        Delningspunkt vid dag {mainTicks[branch.afterIndex].day}
                      </span>
                      <span className="s">
                        Version A och B delar seed ({seed}) och population (
                        {population.name}) fram till denna punkt.
                      </span>
                      {!configLocked ? (
                        <button type="button" onClick={() => setBranch(null)}>
                          Ta bort gren
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div className="branches-grid">
                    <div>
                      <div className="branch-head">
                        <span className="branch-badge a">A</span>
                        <span className="lbl">Version A</span>
                      </div>
                      <TickColumn
                        ticks={branch.a}
                        openKey={openKey}
                        setOpenKey={setOpenKey}
                        updateTick={(i, n) => updateBranchTick("a", i, n)}
                        removeTick={(i) => removeBranchTick("a", i)}
                        moveTick={(i, d) => moveBranchTick("a", i, d)}
                        addTick={() => addBranchTick("a")}
                        onBranch={() => undefined}
                        branchable={false}
                      />
                    </div>
                    <div>
                      <div className="branch-head">
                        <span className="branch-badge b">B</span>
                        <span className="lbl">Version B</span>
                      </div>
                      <TickColumn
                        ticks={branch.b}
                        openKey={openKey}
                        setOpenKey={setOpenKey}
                        updateTick={(i, n) => updateBranchTick("b", i, n)}
                        removeTick={(i) => removeBranchTick("b", i)}
                        moveTick={(i, d) => moveBranchTick("b", i, d)}
                        addTick={() => addBranchTick("b")}
                        onBranch={() => undefined}
                        branchable={false}
                      />
                    </div>
                  </div>
                </>
              )}
            </div>

            <Card className="start-card gap-0 ring-1 ring-border">
              <CardContent className="flex flex-wrap items-center justify-between gap-6 px-8 py-7">
                <div className="start-summary">
                  <div className="start-stat">
                    <div className="n">{tickCount}</div>
                    <div className="l">Tickar</div>
                  </div>
                  <div className="start-stat">
                    <div className="n">{population.size}</div>
                    <div className="l">Personas</div>
                  </div>
                  <div className="start-stat">
                    <div className="n">{variantCount}</div>
                    <div className="l">Varianter</div>
                  </div>
                </div>
                <div className="start-actions">
                  <div className="start-buttons">
                    <button
                      type="button"
                      className="btn-save"
                      disabled={saving || configLocked}
                      onClick={() => void saveDraft(false)}
                    >
                      Spara körning
                    </button>
                    <button
                      type="button"
                      className="btn-run"
                      disabled={saving || configLocked}
                      onClick={() => void saveDraft(true)}
                    >
                      {runStatus === "done" || runStatus === "failed"
                        ? "Kör igen"
                        : "Starta körning"}
                    </button>
                  </div>
                  <button
                    type="button"
                    className="preflight-link"
                    onClick={() => showToast("Pre-flight kommer i en senare fas")}
                  >
                    Kör pre-flight-check först
                  </button>
                </div>
              </CardContent>
            </Card>
          </div>
        ) : (
          <div
            role="tabpanel"
            id="run-panel-results"
            aria-labelledby="run-tab-results"
          >
            {runStatus === "running" ? (
              <Card className="mb-6 gap-0 ring-1 ring-border">
                <CardContent className="px-5 py-6">
                  <h2 className="mb-2 text-base font-semibold text-foreground">
                    Simulering pågår
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Körningen körs som bakgrundsjobb
                    {results ? " — tidigare resultat behålls nedan" : ""}. Du kan
                    lämna sidan.
                  </p>
                  <p className="mt-3 text-sm">
                    <Link to="/jobs" className="text-db-gold-700 underline-offset-2 hover:underline">
                      Visa bakgrundsjobb →
                    </Link>
                  </p>
                </CardContent>
              </Card>
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
                onDeleteAttempt={
                  runId ? (id) => void handleDeleteAttempt(id) : undefined
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
    </AdminShell>
  )
}
