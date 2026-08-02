import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { deleteRun, duplicateRun, listRuns } from "@/api/runs"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { formatRunDate, RUN_STATUS_LABEL } from "@/data/runs"
import type { RunStatus, RunSummary } from "@/data/runs-types"
import { ApiError } from "@/lib/api"

type RunCardProps = {
  run: RunSummary
  onDelete: (id: number) => void
  onDuplicate: (id: number, name: string) => void
}

function RunCard({ run, onDelete, onDuplicate }: RunCardProps) {
  return (
    <div className="run-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="run-inner px-4">
          <div className="run-top">
            <div className="run-nm">{run.name}</div>
            <span className={"status-tag " + run.status}>
              {RUN_STATUS_LABEL[run.status]}
            </span>
          </div>
          <div className="run-meta">
            Population: <b>{run.population}</b>
          </div>
          <div className="run-details">
            <div className="row">
              <span>Tickar</span>
              <span className="v">{run.ticks}</span>
            </div>
            <div className="row">
              <span>Varianter</span>
              <span className="v">
                {run.variants > 1 ? (
                  <span className="variant-badges">
                    <span className="vb a">A</span>
                    <span className="vb b">B</span>
                  </span>
                ) : (
                  "1"
                )}
              </span>
            </div>
            <div className="row">
              <span>Seed</span>
              <span className="v seed mono">{run.seed}</span>
            </div>
            <div className="row">
              <span>Uppdaterad</span>
              <span className="v">{formatRunDate(run.updated)}</span>
            </div>
          </div>
          <div className="run-actions">
            {run.status === "draft" ? (
              <Link className="primary full" to={`/runs/${run.id}/edit`}>
                Fortsätt konfigurera
              </Link>
            ) : (
              <>
                <Link className="primary" to={`/runs/${run.id}/edit`}>
                  {run.status === "running"
                    ? "Se status"
                    : run.status === "failed"
                      ? "Se fel"
                      : "Öppna resultat"}
                </Link>
                <Link to={`/runs/${run.id}/edit`}>Redigera</Link>
              </>
            )}
            <button type="button" onClick={() => onDuplicate(run.id, run.name)}>
              Duplicera
            </button>
            <button type="button" onClick={() => onDelete(run.id)}>
              Ta bort
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<"all" | RunStatus>("all")
  const [sort, setSort] = useState<"updated" | "ticks">("updated")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listRuns()
      .then((data) => {
        if (!cancelled) {
          setRuns(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Kunde inte hämta körningar")
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const list = useMemo(() => {
    let next = runs.filter(
      (r) =>
        r.name.toLowerCase().includes(query.toLowerCase()) &&
        (status === "all" || r.status === status),
    )
    if (sort === "updated") {
      next = [...next].sort(
        (a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime(),
      )
    }
    if (sort === "ticks") {
      next = [...next].sort((a, b) => b.ticks - a.ticks)
    }
    return next
  }, [runs, query, status, sort])

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2400)
  }

  async function handleDelete(id: number) {
    try {
      await deleteRun(id)
      setRuns((prev) => prev.filter((x) => x.id !== id))
      showToast("Körning borttagen")
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte ta bort")
    }
  }

  async function handleDuplicate(id: number, name: string) {
    try {
      const copy = await duplicateRun(id)
      setRuns((prev) => [copy, ...prev])
      showToast(`Duplicerade '${name}'`)
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte duplicera")
    }
  }

  return (
    <AdminShell>
      <div className="wrap">
        <div className="head-row">
          <div>
            <h1>Körningar</h1>
            <div
              style={{
                font: "var(--text-body-sm)",
                color: "var(--text-muted)",
                marginTop: 6,
                maxWidth: 640,
              }}
            >
              Tidigare och pågående simuleringskörningar.
            </div>
          </div>
        </div>

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        <div className="controls-row">
          <div className="controls-left">
            <input
              className="dsearch"
              placeholder="Sök på namn..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              className="dsel"
              value={status}
              onChange={(e) => setStatus(e.target.value as "all" | RunStatus)}
            >
              <option value="all">Alla statusar</option>
              <option value="done">Klara</option>
              <option value="running">Pågår</option>
              <option value="draft">Utkast</option>
              <option value="failed">Misslyckade</option>
            </select>
            <select
              className="dsel"
              value={sort}
              onChange={(e) => setSort(e.target.value as "updated" | "ticks")}
            >
              <option value="updated">Sortera: Senast uppdaterad</option>
              <option value="ticks">Sortera: Flest tickar</option>
            </select>
          </div>
          <Link
            to="/runs/new"
            className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
          >
            + Ny körning
          </Link>
        </div>

        {loading ? (
          <div className="no-match">Hämtar körningar…</div>
        ) : (
          <div className="run-grid">
            {list.length ? (
              list.map((run) => (
                <RunCard
                  key={run.id}
                  run={run}
                  onDelete={handleDelete}
                  onDuplicate={handleDuplicate}
                />
              ))
            ) : (
              <div className="no-match">Inga körningar matchar filtret.</div>
            )}
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
