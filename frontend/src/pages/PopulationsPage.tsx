import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  deletePopulation,
  duplicatePopulation,
  listPopulations,
} from "@/api/populations"
import { AdminShell } from "@/components/layout/AdminShell"
import { Card, CardContent } from "@/components/ui/card"
import { FP_COLORS, formatLibraryDate } from "@/data/library"
import type { PopulationSummary } from "@/data/library-types"
import { ApiError } from "@/lib/api"

type PopCardProps = {
  pop: PopulationSummary
  onDelete: (id: number) => void
  onDup: (id: number, name: string) => void
}

function PopCard({ pop, onDelete, onDup }: PopCardProps) {
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="pop-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="pop-inner px-4">
          <div className="top">
            <div className="nm">{pop.name}</div>
            {pop.versions > 1 && (
              <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
                {pop.versions} versioner
              </span>
            )}
          </div>
          <div className="meta-line">
            <b>{pop.size}</b> personas · uppdaterad {formatLibraryDate(pop.updated)}
          </div>
          <div className="fingerprint">
            {(["ålder", "lutn.", "ort"] as const).map((label, i) => (
              <div className="fp-row" key={label}>
                <div className="fp-lbl">{label}</div>
                <div className="fp-bar">
                  {(pop.fp[i] ?? [0, 0, 0]).map((v, j) => (
                    <span
                      key={j}
                      style={{ width: v + "%", background: FP_COLORS[j] }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="usage-row">
            {pop.runs > 0 ? (
              <span>
                Använd i <b>{pop.runs}</b> körningar
              </span>
            ) : (
              <span className="unused">Oanvänd ännu</span>
            )}
          </div>
          {confirming ? (
            <div className="confirm-row" style={{ marginTop: "auto" }}>
              <button type="button" style={{ flex: 1 }} onClick={() => setConfirming(false)}>
                Avbryt
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(pop.id)}
              >
                Ta bort?
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/populations/${pop.id}`}>
                Öppna
              </Link>
              <button type="button" onClick={() => onDup(pop.id, pop.name)}>
                Duplicera
              </button>
              <Link to={`/populations/${pop.id}/edit`}>Redigera recept</Link>
              <button type="button" className="danger" onClick={() => setConfirming(true)}>
                Ta bort
              </button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function PopulationsPage() {
  const [pops, setPops] = useState<PopulationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [sort, setSort] = useState<"updated" | "size" | "runs">("updated")
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listPopulations()
      .then((data) => {
        if (!cancelled) {
          setPops(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Kunde inte hämta populationer")
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
    let next = pops.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))
    if (sort === "updated") {
      next = [...next].sort(
        (a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime(),
      )
    }
    if (sort === "size") next = [...next].sort((a, b) => b.size - a.size)
    if (sort === "runs") next = [...next].sort((a, b) => b.runs - a.runs)
    return next
  }, [pops, query, sort])

  function showToast(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2400)
  }

  async function handleDelete(id: number) {
    try {
      await deletePopulation(id)
      setPops((prev) => prev.filter((x) => x.id !== id))
      showToast("Population borttagen")
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte ta bort")
    }
  }

  async function handleDup(id: number, name: string) {
    try {
      const copy = await duplicatePopulation(id)
      setPops((prev) => [copy, ...prev])
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
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
                margin: 0,
              }}
            >
              Populationer
            </h1>
            <div
              style={{
                font: "var(--text-body-sm)",
                color: "var(--text-muted)",
                marginTop: 6,
                maxWidth: 640,
              }}
            >
              Sparade demografiska recept och deras genererade personas.
            </div>
          </div>
        </div>

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        {loading ? (
          <div className="no-match">Hämtar populationer…</div>
        ) : pops.length > 0 ? (
          <>
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
                  value={sort}
                  onChange={(e) =>
                    setSort(e.target.value as "updated" | "size" | "runs")
                  }
                >
                  <option value="updated">Sortera: Senast uppdaterad</option>
                  <option value="size">Sortera: Flest personas</option>
                  <option value="runs">Sortera: Flest körningar</option>
                </select>
              </div>
              <Link
                to="/populations/new"
                className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
              >
                + Ny population
              </Link>
            </div>
            <div className="pop-grid">
              {list.length ? (
                list.map((p) => (
                  <PopCard
                    key={p.id}
                    pop={p}
                    onDelete={handleDelete}
                    onDup={handleDup}
                  />
                ))
              ) : (
                <div className="no-match">Inga populationer matchar &quot;{query}&quot;.</div>
              )}
            </div>
          </>
        ) : (
          <div className="empty-state">
            <h2 style={{ font: "var(--text-h2)", marginBottom: 10 }}>
              Inga populationer ännu
            </h2>
            <p style={{ color: "var(--text-muted)", marginBottom: 24 }}>
              En population är ett sparat demografiskt recept med tillhörande
              personas. Skapa den första för att börja testa budskap mot en
              definierad grupp.
            </p>
            <Link
              to="/populations/new"
              className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline"
            >
              + Ny population
            </Link>
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
