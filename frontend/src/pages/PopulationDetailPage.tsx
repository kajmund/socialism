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

/** Fallback when recipe.dist is missing (legacy populations). */
function fpLegendFallback(t: Translate): string[][] {
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
      t("populations.detail.legendOther"),
    ],
  ]
}

const FP_GROUP_KEYS = ["age", "leaning", "district"] as const

function achievedValuesForSection(
  pop: PopulationDetail,
  sectionIndex: number,
): { labels: string[]; values: number[] } {
  const groupKey = FP_GROUP_KEYS[sectionIndex]
  const group = pop.dist_qa.find((g) => g.key === groupKey)
  if (group && group.rows.length > 0) {
    return {
      labels: group.rows.map((r) => r.l),
      values: group.rows.map((r) => r.achieved_v),
    }
  }
  return {
    labels: [],
    values: pop.fp[sectionIndex] ?? [0, 0, 0],
  }
}

function targetValuesForSection(
  pop: PopulationDetail,
  sectionIndex: number,
): { labels: string[]; values: number[] } {
  const groupKey = FP_GROUP_KEYS[sectionIndex]
  const group = pop.dist_qa.find((g) => g.key === groupKey)
  if (group && group.rows.length > 0) {
    return {
      labels: group.rows.map((r) => r.l),
      values: group.rows.map((r) => r.target_v),
    }
  }
  return {
    labels: [],
    values: pop.target_fp[sectionIndex] ?? [],
  }
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
  const [memberView, setMemberView] = useState<"grid" | "lista">("grid")
  const [toast, setToast] = useState<string | null>(null)

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2400)
  }

  function handleRemoveMember(populationIdForRemove: number, member: PopulationMember) {
    if (member.member_id == null) {
      showToast(t("populations.detail.removeMissingId"))
      return
    }
    const memberId = member.member_id
    void removePopulationMember(populationIdForRemove, memberId)
      .then(() => getPopulation(populationIdForRemove))
      .then((data) => {
        setPop(data)
        setMembers(data.members)
      })
      .catch((err: unknown) =>
        showToast(err instanceof ApiError ? err.message : t("common.deleteError")),
      )
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
        <div className="wrap wrap-full">
          <div className="no-match">{t("populations.detail.loading")}</div>
        </div>
      </AdminShell>
    )
  }

  if (notFound || !pop) return <Navigate to="/populations" replace />

  const excludeNames = members.map((m) => m.name)
  const sectionLabels = fpSectionLabels(t)
  const legendFallback = fpLegendFallback(t)

  return (
    <AdminShell>
      <div className="wrap wrap-full">
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

        {pop.qa_warnings.length > 0 && (
          <div
            className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950"
            role="status"
          >
            <strong>{t("populations.detail.qaTitle")}</strong>
            <ul className="mt-2 list-disc pl-5">
              {pop.qa_warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}

        {pop.fingerprint_inferred && (
          <p className="mb-4 text-sm text-[color:var(--text-muted)]">
            {t("populations.detail.fingerprintInferred")}
          </p>
        )}

        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("populations.detail.achievedTitle")}
        </h2>
        <div className="fp-section">
          {sectionLabels.map((label, i) => {
            const achieved = achievedValuesForSection(pop, i)
            const labels = achieved.labels.length > 0 ? achieved.labels : (legendFallback[i] ?? [])
            const values = achieved.values
            return (
              <Card
                className="fp-card gap-0 py-4 ring-1 ring-border"
                key={`achieved-${label}`}
                style={{ gridColumn: "span 2" }}
              >
                <CardContent className="px-5">
                  <h4>{label}</h4>
                  <div className="fp-bar">
                    {values.map((v, j) => (
                      <span
                        key={j}
                        style={{
                          width: v + "%",
                          background: FP_COLORS[j % FP_COLORS.length],
                        }}
                      />
                    ))}
                  </div>
                  <div className="fp-legend">
                    {labels.map((l, j) => (
                      <div className="row" key={`achieved-${i}-${j}-${l}`}>
                        <div
                          className="dot"
                          style={{ background: FP_COLORS[j % FP_COLORS.length] }}
                        />
                        {l} — {values[j] ?? 0}%
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>

        <h2 className="mb-2 mt-6 text-sm font-medium uppercase tracking-wide text-[color:var(--text-muted)]">
          {t("populations.detail.targetTitle")}
        </h2>
        <div className="fp-section">
          {sectionLabels.map((label, i) => {
            const target = targetValuesForSection(pop, i)
            const achieved = achievedValuesForSection(pop, i)
            const labels = target.labels.length > 0 ? target.labels : (legendFallback[i] ?? [])
            const values = target.values.length > 0 ? target.values : (pop.target_fp[i] ?? [])
            return (
              <Card
                className="fp-card gap-0 py-4 ring-1 ring-border opacity-90"
                key={`target-${label}`}
                style={{ gridColumn: "span 2" }}
              >
                <CardContent className="px-5">
                  <h4>{label}</h4>
                  <div className="fp-bar">
                    {values.map((v, j) => (
                      <span
                        key={j}
                        style={{
                          width: v + "%",
                          background: FP_COLORS[j % FP_COLORS.length],
                        }}
                      />
                    ))}
                  </div>
                  <div className="fp-legend">
                    {labels.map((l, j) => {
                      const achievedV = achieved.values[j]
                      const targetV = values[j] ?? 0
                      const delta =
                        typeof achievedV === "number" ? Math.abs(achievedV - targetV) : 0
                      return (
                        <div className="row" key={`target-${i}-${j}-${l}`}>
                          <div
                            className="dot"
                            style={{ background: FP_COLORS[j % FP_COLORS.length] }}
                          />
                          {l} — {targetV}%
                          {typeof achievedV === "number" && delta > 0
                            ? ` (${t("populations.detail.targetDiff", {
                                achieved: achievedV,
                                delta,
                              })})`
                            : ""}
                        </div>
                      )
                    })}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>

        <div className="section-title">
          <h2>{t("populations.detail.membersTitle")}</h2>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {members.length > 0 ? (
              <div className="view-toggle">
                <button
                  type="button"
                  className={memberView === "grid" ? "on" : ""}
                  onClick={() => setMemberView("grid")}
                >
                  {t("populations.detail.gridView")}
                </button>
                <button
                  type="button"
                  className={memberView === "lista" ? "on" : ""}
                  onClick={() => setMemberView("lista")}
                >
                  {t("populations.detail.listView")}
                </button>
              </div>
            ) : null}
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
                .then(() => getPopulation(pop.id))
                .then((data) => {
                  setPop(data)
                  setMembers(data.members)
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
        ) : memberView === "grid" ? (
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
                        onClick={() => handleRemoveMember(pop.id, p)}
                      >
                        {t("populations.detail.remove")}
                      </button>
                    </div>
                  </CardContent>
                </Card>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-list population-member-list">
            {members.map((p) => (
              <div
                className="p-row"
                key={p.member_id ?? `${p.name}-${p.id ?? "x"}`}
              >
                <Link
                  to={p.id ? `/personas/${p.id}` : "/personas"}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    minWidth: 0,
                    color: "inherit",
                    textDecoration: "none",
                  }}
                >
                  <div className="av" style={{ width: 28, height: 28, fontSize: 11 }}>
                    {p.initials}
                  </div>
                  <div className="nm2">{p.name}</div>
                </Link>
                <div className="quote2">{p.trait || t("common.emDash")}</div>
                <div className="meta">
                  {p.age} · {p.occ} · {p.district}
                </div>
                <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                  <Link to={p.id ? `/personas/${p.id}` : "/personas"}>
                    {t("common.open")}
                  </Link>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => handleRemoveMember(pop.id, p)}
                  >
                    {t("populations.detail.remove")}
                  </button>
                </div>
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
