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
import { FP_COLORS, formatLibraryDate, libraryPersonaToMember } from "@/data/library"
import type { PopulationMember } from "@/data/library-types"
import { useLocale, type MessageKey } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string

function fpSectionLabels(t: Translate): [string, string, string] {
  return [
    t("populations.detail.fpAge"),
    t("populations.detail.fpLean"),
    t("populations.detail.fpDistrict"),
  ]
}

function fpLegendLabels(t: Translate): [string, string, string][] {
  return [
    [
      t("populations.detail.legendYoung"),
      t("populations.detail.legendMid"),
      t("populations.detail.legendOld"),
    ],
    [
      t("populations.detail.legendLeft"),
      t("populations.detail.legendCenter"),
      t("populations.detail.legendRight"),
    ],
    [
      t("populations.detail.legendCentrum"),
      t("populations.detail.legendDistrictA"),
      t("populations.detail.legendOther"),
    ],
  ]
}

export function PopulationDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { t, intl } = useLocale()
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
        else showToast(err instanceof ApiError ? err.message : t("populations.detail.loadError"))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [populationId, t])

  if (loading) {
    return (
      <AdminShell>
        <div className="wrap">
          <div className="no-match">{t("populations.detail.loading")}</div>
        </div>
      </AdminShell>
    )
  }

  if (notFound || !pop) return <Navigate to="/populations" replace />

  const excludeNames = members.map((m) => m.name)
  const sectionLabels = fpSectionLabels(t)
  const legendLabels = fpLegendLabels(t)

  return (
    <AdminShell>
      <div className="wrap">
        <div className="crumb">
          <Link to="/populations">{t("populations.detail.back")}</Link>
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
                    showToast(t("populations.detail.duplicated", { name: pop.name }))
                    navigate(`/populations/${copy.id}`)
                  })
                  .catch((err: unknown) =>
                    showToast(
                      err instanceof ApiError ? err.message : t("common.duplicateError"),
                    ),
                  )
              }}
            >
              {t("common.duplicate")}
            </AdminButton>
            <Link to={`/populations/${pop.id}/edit`} className="no-underline">
              <AdminButton variant="primary" size="sm">
                {t("common.editRecipe")}
              </AdminButton>
            </Link>
          </div>
        </div>
        <div className="head-meta">
          <span>
            <b>{members.length}</b> {t("common.personas")}
          </span>
          <span>
            {t("common.updated", { when: formatLibraryDate(pop.updated, intl) })}
          </span>
          <span>
            {pop.runs > 0 ? (
              <>
                {t("populations.detail.usedInPrefix")} <b>{pop.runs}</b>{" "}
                {t("populations.detail.usedInSuffix")}
              </>
            ) : (
              <i>{t("populations.detail.unused")}</i>
            )}
          </span>
          {pop.versions > 1 && (
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {t("common.versions", { count: pop.versions })}
            </span>
          )}
        </div>

        <div className="fp-section">
          {sectionLabels.map((label, i) => (
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
                  {legendLabels[i].map((l, j) => (
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
          <h2>{t("populations.detail.membersTitle")}</h2>
          <button
            type="button"
            className="add-lib-toggle"
            onClick={() => setShowAdd((v) => !v)}
          >
            {showAdd
              ? t("populations.detail.hideLibrary")
              : t("populations.detail.showLibrary")}
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
                  showToast(t("populations.detail.added", { name: p.name, pop: pop.name }))
                })
                .catch((err: unknown) =>
                  showToast(err instanceof ApiError ? err.message : t("common.addError")),
                )
            }}
          />
        )}

        {members.length === 0 ? (
          <div className="no-match" style={{ textAlign: "left", padding: "20px 0" }}>
            {t("populations.detail.emptyMembers")}
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
                        {t("common.openArrow")}
                      </Link>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => {
                          if (p.member_id == null) {
                            showToast(t("populations.detail.removeMissingId"))
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
                                err instanceof ApiError
                                  ? err.message
                                  : t("common.deleteError"),
                              ),
                            )
                        }}
                      >
                        {t("populations.detail.remove")}
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
