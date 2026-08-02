import { useEffect, useState } from "react"
import { Link, Navigate, useNavigate, useParams } from "react-router-dom"
import {
  addPopulationMember,
  duplicatePopulation,
  getPopulation,
  removePopulationMember,
  type PopulationDetail,
} from "@/api/populations"
import { AdminShell } from "@/components/layout/AdminShell"
import { AddFromLibraryPanel } from "@/components/populations/AddFromLibraryPanel"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import {
  FP_COLORS,
  FP_DETAIL_LABELS,
  formatLibraryDate,
  libraryPersonaToMember,
} from "@/data/library"
import type { PopulationMember } from "@/data/library-types"
import { ApiError } from "@/lib/api"

export function PopulationDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const populationId = id ? Number(id) : NaN

  const [pop, setPop] = useState<PopulationDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [members, setMembers] = useState<PopulationMember[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2400)
  }

  useEffect(() => {
    if (!Number.isFinite(populationId)) {
      setNotFound(true)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    getPopulation(populationId)
      .then((data) => {
        if (cancelled) return
        setPop(data)
        setMembers(data.members)
        setNotFound(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) setNotFound(true)
        else showToast(err instanceof ApiError ? err.message : "Kunde inte hämta population")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [populationId])

  if (loading) {
    return (
      <AdminShell>
        <div className="wrap">
          <div className="no-match">Hämtar population…</div>
        </div>
      </AdminShell>
    )
  }

  if (notFound || !pop) return <Navigate to="/populations" replace />

  const excludeNames = members.map((m) => m.name)

  return (
    <AdminShell>
      <div className="wrap">
        <div className="crumb">
          <Link to="/populations">← Populationer</Link>
        </div>
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
              {pop.name}
            </h1>
          </div>
          <div className="head-actions">
            <AdminButton
              variant="secondary"
              size="sm"
              onClick={() => {
                void duplicatePopulation(pop.id)
                  .then((copy) => {
                    showToast(`Duplicerade '${pop.name}'`)
                    navigate(`/populations/${copy.id}`)
                  })
                  .catch((err: unknown) =>
                    showToast(err instanceof ApiError ? err.message : "Kunde inte duplicera"),
                  )
              }}
            >
              Duplicera
            </AdminButton>
            <Link to={`/populations/${pop.id}/edit`} className="no-underline">
              <AdminButton variant="primary" size="sm">
                Redigera recept
              </AdminButton>
            </Link>
          </div>
        </div>
        <div className="head-meta">
          <span>
            <b>{members.length}</b> personas
          </span>
          <span>uppdaterad {formatLibraryDate(pop.updated)}</span>
          <span>
            {pop.runs > 0 ? (
              <>
                använd i <b>{pop.runs}</b> körningar
              </>
            ) : (
              <i>Oanvänd ännu</i>
            )}
          </span>
          {pop.versions > 1 && (
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {pop.versions} versioner
            </span>
          )}
        </div>

        <div className="fp-section">
          {(["Ålder", "Politisk lutning", "Ort"] as const).map((label, i) => (
            <Card
              className="fp-card gap-0 py-4 ring-1 ring-border"
              key={label}
              style={{ gridColumn: "span 2" }}
            >
              <CardContent className="px-5">
                <h4>{label}</h4>
                <div className="fp-bar">
                  {(pop.fp[i] ?? [0, 0, 0]).map((v, j) => (
                    <span
                      key={j}
                      style={{ width: v + "%", background: FP_COLORS[j] }}
                    />
                  ))}
                </div>
                <div className="fp-legend">
                  {FP_DETAIL_LABELS[i].map((l, j) => (
                    <div className="row" key={l}>
                      <div className="dot" style={{ background: FP_COLORS[j] }} />
                      {l} — {pop.fp[i]?.[j] ?? 0}%
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="section-title">
          <h2>Personas i populationen</h2>
          <button
            type="button"
            className="add-lib-toggle"
            onClick={() => setShowAdd((v) => !v)}
          >
            {showAdd ? "Dölj bibliotek ←" : "+ Lägg till från bibliotek →"}
          </button>
        </div>

        {showAdd && (
          <AddFromLibraryPanel
            excludeNames={excludeNames}
            onAdd={(p) => {
              const member = libraryPersonaToMember(p)
              void addPopulationMember(pop.id, {
                persona_id: p.id,
                name: member.name,
                initials: member.initials,
                age: member.age,
                occ: member.occ,
                district: member.district,
                trait: member.trait,
              })
                .then((added) => {
                  setMembers((prev) => [...prev, added])
                  setPop((prev) =>
                    prev ? { ...prev, size: prev.size + 1 } : prev,
                  )
                  showToast(`La till ${p.name} i ${pop.name}`)
                })
                .catch((err: unknown) =>
                  showToast(err instanceof ApiError ? err.message : "Kunde inte lägga till"),
                )
            }}
          />
        )}

        {members.length === 0 ? (
          <div className="no-match" style={{ textAlign: "left", padding: "20px 0" }}>
            Inga personas i den här populationen ännu. Lägg till från biblioteket
            eller generera via receptet.
          </div>
        ) : (
          <div className="p-grid">
            {members.map((p) => (
              <div className="pcard" key={p.member_id ?? `${p.name}-${p.id ?? "x"}`}>
                <Card className="h-full gap-0 py-4 ring-1 ring-border">
                  <CardContent className="pcard-inner px-4">
                    <div className="ph">
                      <div className="av">{p.initials}</div>
                      <div style={{ minWidth: 0 }}>
                        <div className="nm">{p.name}</div>
                        <div className="meta">
                          {p.age} · {p.occ} · {p.district}
                        </div>
                      </div>
                    </div>
                    <div className="trait">{p.trait}</div>
                    <div className="actions">
                      <Link to={p.id ? `/personas/${p.id}` : "/personas"}>
                        Öppna →
                      </Link>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => {
                          if (p.member_id == null) {
                            showToast("Kunde inte ta bort — saknar medlems-id")
                            return
                          }
                          const memberId = p.member_id
                          void removePopulationMember(pop.id, memberId)
                            .then(() => {
                              setMembers((prev) =>
                                prev.filter((m) => m.member_id !== memberId),
                              )
                              setPop((prev) =>
                                prev ? { ...prev, size: Math.max(0, prev.size - 1) } : prev,
                              )
                            })
                            .catch((err: unknown) =>
                              showToast(
                                err instanceof ApiError ? err.message : "Kunde inte ta bort",
                              ),
                            )
                        }}
                      >
                        ✕ Ta bort
                      </button>
                    </div>
                  </CardContent>
                </Card>
              </div>
            ))}
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
