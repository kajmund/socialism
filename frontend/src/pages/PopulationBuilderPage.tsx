import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { listCatalog, type CatalogList } from "@/api/catalog"
import { createJob } from "@/api/jobs"
import { getPopulation, type DistRow, type PopulationRecipe } from "@/api/populations"
import { AdminShell, rememberJobPending } from "@/components/layout/AdminShell"
import { AddFromLibraryPanel } from "@/components/populations/AddFromLibraryPanel"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { personaInitials } from "@/data/library"
import type { LibraryPersona } from "@/data/library-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translator = (key: MessageKey, params?: TranslateParams) => string

const STEP_TITLES = [
  "populations.builder.stepStart",
  "populations.builder.stepDistributions",
  "populations.builder.stepPreview",
] as const satisfies readonly MessageKey[]
/** Palette uses tokens that exist on `.theme-admin` (ink-600 / gold-300 do not). */
const ROW_COLORS = [
  "var(--db-ink-950)",
  "var(--db-gold-500)",
  "var(--db-ink-400)",
  "var(--db-gold-700)",
  "var(--db-navy-ink)",
  "var(--db-ink-200)",
  "var(--db-success)",
  "var(--db-error)",
  "var(--db-gold-100)",
]

type DistGroupData = { label: string; rows: DistRow[] }
type DistState = Record<string, DistGroupData>

/** Catalog keys → builder distribution groups (age stays local — not in catalog). */
const CATALOG_DIST_MAP: {
  catalogKey: string
  groupKey: string
  fallbackKey: MessageKey
}[] = [
  { catalogKey: "kön", groupKey: "kön", fallbackKey: "populations.builder.distGender" },
  { catalogKey: "ort", groupKey: "district", fallbackKey: "populations.builder.distDistrict" },
  { catalogKey: "yrke", groupKey: "occupation", fallbackKey: "populations.builder.distOccupation" },
  { catalogKey: "utbildning", groupKey: "education", fallbackKey: "populations.builder.distEducation" },
  { catalogKey: "livssituation", groupKey: "livssituation", fallbackKey: "populations.builder.distLifeSituation" },
  { catalogKey: "lutning", groupKey: "leaning", fallbackKey: "populations.builder.distPoliticalLean" },
  { catalogKey: "parti", groupKey: "parti", fallbackKey: "populations.builder.distParty" },
  { catalogKey: "valdeltagande", groupKey: "valdeltagande", fallbackKey: "populations.builder.distTurnout" },
  { catalogKey: "sakfragor", groupKey: "sakfragor", fallbackKey: "populations.builder.distIssues" },
  { catalogKey: "fortroende", groupKey: "fortroende", fallbackKey: "populations.builder.distTrust" },
  { catalogKey: "ton", groupKey: "ton", fallbackKey: "populations.builder.distTone" },
  { catalogKey: "sprak", groupKey: "sprak", fallbackKey: "populations.builder.distLanguage" },
  { catalogKey: "medievanor", groupKey: "media", fallbackKey: "populations.builder.distMedia" },
]

function mergeMissingDist(base: DistState, extras: DistState): DistState {
  const next: DistState = { ...base }
  for (const [key, group] of Object.entries(extras)) {
    if (!(key in next)) next[key] = group
  }
  return next
}

function buildAgeGroup(t: Translator): DistGroupData {
  return {
    label: t("populations.builder.ageGroup"),
    rows: [
      { k: "ung", l: t("populations.builder.ageYoung"), v: 30 },
      { k: "medel", l: t("populations.builder.ageMiddle"), v: 45 },
      { k: "aldre", l: t("populations.builder.ageOlder"), v: 25 },
    ],
  }
}

function slugifyLabel(label: string): string {
  return label
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
}

function equalWeightRows(labels: string[]): DistRow[] {
  const n = labels.length || 1
  const base = Math.floor(100 / n)
  const rem = 100 - base * n
  return labels.map((label, i) => ({
    k: slugifyLabel(label) || `row_${i}`,
    l: label,
    v: base + (i === 0 ? rem : 0),
  }))
}

function distFromCatalog(lists: CatalogList[], t: Translator): DistState {
  const byKey = new Map(lists.map((list) => [list.key, list]))
  const ageGroup = buildAgeGroup(t)
  const dist: DistState = {
    age: { label: ageGroup.label, rows: ageGroup.rows.map((r) => ({ ...r })) },
  }
  for (const { catalogKey, groupKey, fallbackKey } of CATALOG_DIST_MAP) {
    const list = byKey.get(catalogKey)
    const labels = (list?.items ?? [])
      .map((item) => item.label.trim())
      .filter(Boolean)
    if (labels.length === 0) continue
    dist[groupKey] = {
      label: list?.title || t(fallbackKey),
      rows: equalWeightRows(labels),
    }
  }
  return dist
}

function DistGroup({
  gkey,
  group,
  onSlide,
}: {
  gkey: string
  group: DistGroupData
  onSlide: (gkey: string, rowKey: string, val: number) => void
}) {
  return (
    <Card className="gap-0 py-5 ring-1 ring-border">
      <CardContent className="px-5">
        <h4 style={{ font: "var(--text-h3)", marginBottom: 12 }}>{group.label}</h4>
        <div className="dist-bar">
          {group.rows.map((r, i) => (
            <span
              key={r.k}
              style={{ width: r.v + "%", background: ROW_COLORS[i % ROW_COLORS.length] }}
            />
          ))}
        </div>
        {group.rows.map((r, i) => {
          const color = ROW_COLORS[i % ROW_COLORS.length]!
          return (
            <div className="dist-row" key={r.k}>
              <div className="dot" style={{ background: color }} />
              <div>
                <div className="lbl">{r.l}</div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={r.v}
                  style={{ accentColor: color }}
                  onChange={(e) => onSlide(gkey, r.k, parseInt(e.target.value, 10))}
                />
              </div>
              <div className="pct">{r.v}%</div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

function PrevGroup({ group }: { group: DistGroupData }) {
  return (
    <Card className="gap-0 py-5 ring-1 ring-border">
      <CardContent className="px-5">
        <h4 style={{ font: "var(--text-h3)", marginBottom: 12 }}>{group.label}</h4>
        <div className="dist-bar">
          {group.rows.map((r, i) => (
            <span
              key={r.k}
              style={{ width: r.v + "%", background: ROW_COLORS[i % ROW_COLORS.length] }}
            />
          ))}
        </div>
        <div className="prev-legend">
          {group.rows.map((r, i) => (
            <div className="row" key={r.k}>
              <div
                className="dot"
                style={{ background: ROW_COLORS[i % ROW_COLORS.length] }}
              />
              <div>{r.l}</div>
              <div className="pct">{r.v}%</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export function PopulationBuilderPage() {
  const { t } = useLocale()
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const editId = id && id !== "new" ? Number(id) : null
  const isEditRecipe = !!editId || params.get("edit") === "1"

  const [cur, setCur] = useState(isEditRecipe ? 2 : 1)
  const [maxReached, setMaxReached] = useState(isEditRecipe ? 3 : 1)
  const [popName, setPopName] = useState(() => t("populations.builder.defaultName"))
  const [popSize, setPopSize] = useState(12)
  const [dist, setDist] = useState<DistState>(() => ({
    age: buildAgeGroup(t),
  }))
  const [catalogReady, setCatalogReady] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedPersonas, setSelectedPersonas] = useState<LibraryPersona[]>([])

  const effectiveSize = Math.max(popSize, selectedPersonas.length)
  const libraryCount = selectedPersonas.length
  const generateCount = Math.max(0, effectiveSize - libraryCount)
  const selectedIds = useMemo(
    () => selectedPersonas.map((p) => p.id),
    [selectedPersonas],
  )
  const stepTitles = useMemo(() => STEP_TITLES.map((key) => t(key)), [t])

  useEffect(() => {
    let cancelled = false
    listCatalog()
      .then((lists) => {
        if (cancelled) return
        const fromCatalog = distFromCatalog(lists, t)
        if (!editId) setDist(fromCatalog)
        else setDist((prev) => mergeMissingDist(prev, fromCatalog))
        setCatalogReady(true)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(
            err instanceof ApiError ? err.message : t("populations.builder.loadCatalogError"),
          )
          setCatalogReady(true)
        }
      })
    return () => {
      cancelled = true
    }
  }, [editId, t])

  useEffect(() => {
    if (!editId) return
    let cancelled = false
    getPopulation(editId)
      .then((pop) => {
        if (cancelled) return
        setPopName(pop.name)
        setPopSize(pop.size || pop.members.length || 12)
        if (pop.recipe && typeof pop.recipe === "object" && "dist" in pop.recipe) {
          const recipeDist = pop.recipe.dist as DistState
          setDist((prev) => mergeMissingDist(recipeDist, prev))
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(
            err instanceof ApiError ? err.message : t("populations.builder.loadPopulationError"),
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [editId, t])

  function buildRecipe(): PopulationRecipe {
    return {
      size: effectiveSize,
      dist,
      locale: "norrkoping",
    }
  }

  function onSlide(gkey: string, rowKey: string, val: number) {
    setDist((prev) => {
      const group = prev[gkey]
      if (!group) return prev
      const next: DistState = {
        ...prev,
        [gkey]: {
          ...group,
          rows: group.rows.map((r) => ({ ...r })),
        },
      }
      const rows = next[gkey]!.rows
      const row = rows.find((r) => r.k === rowKey)
      if (!row) return prev
      const others = rows.filter((r) => r.k !== rowKey)
      const othersSum = others.reduce((a, r) => a + r.v, 0)
      const remaining = 100 - val
      row.v = val
      if (othersSum > 0) {
        others.forEach((r) => {
          r.v = Math.round((r.v * remaining) / othersSum)
        })
      }
      const diff = 100 - rows.reduce((a, r) => a + r.v, 0)
      if (others[0]) others[0].v += diff
      else row.v += diff
      return next
    })
  }

  async function startGenerationJob() {
    setSubmitting(true)
    setLoadError(null)
    const name = popName.trim() || t("populations.builder.fallbackName")
    try {
      const job = await createJob({
        kind: "population_generate",
        label: name,
        request: {
          name,
          recipe: buildRecipe(),
          population_id: editId,
          include_persona_ids: selectedIds,
        },
      })
      rememberJobPending(job.id)
      navigate("/jobs")
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("populations.builder.startJobError"),
      )
    } finally {
      setSubmitting(false)
    }
  }

  function addLibraryPersona(persona: LibraryPersona) {
    setSelectedPersonas((prev) =>
      prev.some((p) => p.id === persona.id) ? prev : [...prev, persona],
    )
  }

  function removeLibraryPersona(id: string) {
    setSelectedPersonas((prev) => prev.filter((p) => p.id !== id))
  }

  function next() {
    if (cur < 3) {
      setCur(cur + 1)
      setMaxReached((m) => Math.max(m, cur + 1))
    }
  }

  function back() {
    if (cur > 1) setCur(cur - 1)
  }

  return (
    <AdminShell>
      <div className="wrap" style={{ maxWidth: 1180 }}>
        {loadError && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {loadError}
          </div>
        )}
        <div className="stepper">
          {stepTitles.map((title, i) => {
            const n = i + 1
            const cls =
              n === cur
                ? "active"
                : n < cur
                  ? "done"
                  : n <= maxReached
                    ? "reachable"
                    : ""
            return (
              <div
                key={n}
                role="button"
                tabIndex={n <= maxReached ? 0 : -1}
                className={"step-pill " + cls}
                onClick={() => {
                  if (n <= maxReached) setCur(n)
                }}
                onKeyDown={(e) => {
                  if (n <= maxReached && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault()
                    setCur(n)
                  }
                }}
              >
                <div className="step-num">{n < cur ? "✓" : n}</div>
                <div className="step-t">{title}</div>
              </div>
            )
          })}
        </div>

        {isEditRecipe && (
          <div
            style={{
              font: "var(--text-body-sm)",
              color: "var(--db-gold-700)",
              marginBottom: 20,
              marginTop: -16,
            }}
          >
            {t("populations.builder.editBanner", { name: popName })}
          </div>
        )}

        {cur === 1 && (
          <section>
            <div className="section-head">
              <span className="kicker">{t("populations.builder.step1Kicker")}</span>
              <h1
                style={{
                  font: "var(--text-h1)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                }}
              >
                {t("populations.builder.step1Title")}
              </h1>
              <p>{t("populations.builder.step1Body")}</p>
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="pop-name">{t("populations.builder.nameLabel")}</label>
                <input
                  id="pop-name"
                  value={popName}
                  onChange={(e) => setPopName(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="pop-size">{t("populations.builder.sizeLabel")}</label>
                <input
                  id="pop-size"
                  type="number"
                  min={4}
                  max={40}
                  value={popSize}
                  onChange={(e) => setPopSize(parseInt(e.target.value, 10) || 12)}
                />
              </div>
            </div>
          </section>
        )}

        {cur === 2 && (
          <section>
            <div className="section-head">
              <span className="kicker">{t("populations.builder.step2Kicker")}</span>
              <h1
                style={{
                  font: "var(--text-h1)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                }}
              >
                {t("populations.builder.step2Title")}
              </h1>
              <p>
                {t("populations.builder.step2BodyPrefix")}{" "}
                <Link to="/configurations" style={{ color: "var(--db-gold-700)" }}>
                  {t("populations.builder.configLink")}
                </Link>
                {t("populations.builder.step2BodySuffix")}
              </p>
            </div>
            {!catalogReady ? (
              <div className="no-match" style={{ textAlign: "left" }}>
                {t("populations.builder.loadingConfig")}
              </div>
            ) : (
              <div className="dist-grid">
                {Object.keys(dist).map((gkey) => (
                  <DistGroup key={gkey} gkey={gkey} group={dist[gkey]!} onSlide={onSlide} />
                ))}
              </div>
            )}
          </section>
        )}

        {cur === 3 && (
          <section>
            <div className="section-head">
              <span className="kicker">{t("populations.builder.step3Kicker")}</span>
              <h1
                style={{
                  font: "var(--text-h1)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                }}
              >
                {t("populations.builder.step3Title")}
              </h1>
              <p>{t("populations.builder.step3Body")}</p>
            </div>
            <div className="prev-grid">
              {Object.keys(dist).map((gkey) => (
                <PrevGroup key={gkey} group={dist[gkey]!} />
              ))}
            </div>

            <div style={{ marginTop: 28, marginBottom: 10 }}>
              <h3 style={{ font: "var(--text-h3)", marginBottom: 6 }}>
                {t("populations.builder.libraryTitle")}
              </h3>
              <p style={{ color: "var(--text-muted)", fontSize: 13.5, marginBottom: 12 }}>
                {effectiveSize !== popSize
                  ? t("populations.builder.librarySummaryRaised", {
                      libraryCount,
                      generateCount,
                      effectiveSize,
                    })
                  : t("populations.builder.librarySummary", {
                      libraryCount,
                      generateCount,
                      effectiveSize,
                    })}
              </p>
              {selectedPersonas.length > 0 && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                    marginBottom: 14,
                  }}
                >
                  {selectedPersonas.map((p) => (
                    <div
                      key={p.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 12,
                        padding: "8px 4px",
                        borderBottom: "1px solid var(--border-hairline)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                        <div className="av">{personaInitials(p.name)}</div>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{p.name}</div>
                          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                            {p.age} · {p.occ} · {p.district}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="add-lib-toggle"
                        onClick={() => removeLibraryPersona(p.id)}
                      >
                        {t("common.delete")}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <AddFromLibraryPanel
                excludeIds={selectedIds}
                onAdd={addLibraryPersona}
                hint={t("populations.builder.libraryHint")}
              />
            </div>

            <div className="run-cta">
              <AdminButton
                variant="accent"
                disabled={submitting}
                onClick={() => void startGenerationJob()}
              >
                {submitting
                  ? t("populations.builder.startingJob")
                  : generateCount === 0
                    ? t("populations.builder.createPopulation")
                    : t("populations.builder.generatePersonas")}
              </AdminButton>
            </div>
          </section>
        )}

        <div className="nav-bar">
          <AdminButton variant="secondary" disabled={cur === 1} onClick={back}>
            {t("common.back")}
          </AdminButton>
          {cur !== 3 && (
            <AdminButton variant="primary" onClick={next}>
              {t("common.next")}
            </AdminButton>
          )}
        </div>
      </div>
    </AdminShell>
  )
}
