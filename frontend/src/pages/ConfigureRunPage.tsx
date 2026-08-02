import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  createRun,
  getRun,
  listRunPopulations,
  startRun,
  updateRun,
} from "@/api/runs"
import { AdminShell } from "@/components/layout/AdminShell"
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

export function ConfigureRunPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const runId = id && id !== "new" ? Number(id) : null

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

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2600)
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
  }, [runId])

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
      const payload = {
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
        : await createRun(payload)
      if (andStart) {
        const started = await startRun(saved.id)
        setRunStatus(started.status)
        setResults(started.results)
        showToast(
          started.status === "failed"
            ? `Körning misslyckades: ${started.results?.error ?? "okänt fel"}`
            : `Körning "${name}" klar`,
        )
        if (started.status === "done" || started.status === "failed") {
          window.setTimeout(() => navigate(`/runs/${started.id}/edit`), 700)
          return
        }
      } else {
        showToast(`Sparade "${name}" som utkast`)
      }
      window.setTimeout(() => navigate("/runs"), 700)
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte spara")
    } finally {
      setSaving(false)
    }
  }

  const activeMain = branch ? mainTicks.slice(0, branch.afterIndex + 1) : mainTicks
  const tickCount =
    mainTicks.length + (branch ? branch.a.length + branch.b.length : 0)
  const variantCount = branch ? 2 : 1

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
            <h1>Konfigurera körning</h1>
            <p>
              Bygg scenariots tidslinje av tickar, koppla en population och starta
              simuleringen.
            </p>
          </div>
        </div>

        <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
          <CardContent className="px-0">
            <div className="id-grid">
              <div className="id-field">
                <label>Namn / scenario-id</label>
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="id-field">
                <label>Startdatum</label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                />
              </div>
              <div className="id-field">
                <label>Seed</label>
                <div className="seed-row">
                  <input
                    className="mono"
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                  />
                  <button
                    type="button"
                    className="seed-refresh"
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
                <div className="pop-mini" onClick={() => setPopOpen(true)}>
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
                            className={"pop-opt" + (p.id === popId ? " sel" : "")}
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
                          <Link to="/populations">Visa alla populationer →</Link>
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
            addTick={branch ? () => undefined : addMain}
            onBranch={startBranch}
            branchable={!branch}
            showAdd={!branch}
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
                  <button type="button" onClick={() => setBranch(null)}>
                    Ta bort gren
                  </button>
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
                  disabled={saving}
                  onClick={() => void saveDraft(false)}
                >
                  Spara körning
                </button>
                <button
                  type="button"
                  className="btn-run"
                  disabled={saving}
                  onClick={() => void saveDraft(true)}
                >
                  Starta körning
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

        {results ? <OasisResultsPanel results={results} status={runStatus} /> : null}
      </div>

      {toast && (
        <div className="fixed bottom-6 right-6 rounded-md bg-db-ink-950 px-4 py-3 text-sm text-db-ink-0 shadow-lg">
          {toast}
        </div>
      )}
    </AdminShell>
  )
}
