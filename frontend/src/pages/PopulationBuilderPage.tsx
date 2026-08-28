import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"
import { listCatalog, type CatalogList } from "@/api/catalog"
import { createJob } from "@/api/jobs"
import { createPopulation, type DistRow, type PopulationRecipe } from "@/api/populations"
import { AdminShell, rememberJobPending } from "@/components/layout/AdminShell"
import { AddFromLibraryPanel } from "@/components/populations/AddFromLibraryPanel"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { personaInitials } from "@/data/library"
import type { LibraryPersona, PersonaKind } from "@/data/library-types"
import { useAuth } from "@/auth/AuthProvider"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"
import { ApiError } from "@/lib/api"

type Translator = (key: MessageKey, params?: TranslateParams) => string

type PopulationBuilderKind = "persona" | "expert_panel"

type PopulationBuilderPageProps = {
  kind?: PopulationBuilderKind
  Shell?: ComponentType<{ children: ReactNode }>
  basePath?: string
}

const PERSONA_STEP_TITLES = [
  "populations.builder.stepStart",
  "populations.builder.stepDistributions",
  "populations.builder.stepPreview",
] as const satisfies readonly MessageKey[]

const EXPERT_PANEL_STEP_TITLES = [
  "expertPanels.builder.stepStart",
  "expertPanels.builder.stepExperts",
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

export function PopulationBuilderPage({
  kind = "persona",
  Shell = AdminShell,
  basePath = "/populations",
}: PopulationBuilderPageProps) {
  const isExpertPanel = kind === "expert_panel"
  const personaKind: PersonaKind = isExpertPanel ? "expert" : "persona"
  const stepKeys = isExpertPanel ? EXPERT_PANEL_STEP_TITLES : PERSONA_STEP_TITLES
  const maxStep = stepKeys.length
  const { t } = useLocale()
  const { isAdmin } = useAuth()
  const navigate = useNavigate()

  const [cur, setCur] = useState(1)
  const [maxReached, setMaxReached] = useState(1)
  const [popName, setPopName] = useState(() =>
    t(isExpertPanel ? "expertPanels.builder.defaultName" : "populations.builder.defaultName"),
  )
  const [popSize, setPopSize] = useState(12)
  const [dist, setDist] = useState<DistState>(() => ({
    age: buildAgeGroup(t),
  }))
  const [catalogReady, setCatalogReady] = useState(isExpertPanel)
  const [submitting, setSubmitting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedPersonas, setSelectedPersonas] = useState<LibraryPersona[]>([])

  const effectiveSize = isExpertPanel
    ? Math.max(1, selectedPersonas.length)
    : Math.max(popSize, selectedPersonas.length)
  const libraryCount = selectedPersonas.length
  const generateCount = isExpertPanel ? 0 : Math.max(0, effectiveSize - libraryCount)
  const selectedIds = useMemo(
    () => selectedPersonas.map((p) => p.id),
    [selectedPersonas],
  )
  const stepTitles = useMemo(() => stepKeys.map((key) => t(key)), [stepKeys, t])

  useEffect(() => {
    if (isExpertPanel) return
    let cancelled = false
    listCatalog()
      .then((lists) => {
        if (cancelled) return
        setDist(distFromCatalog(lists, t))
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
  }, [isExpertPanel, t])

  function buildRecipe(): PopulationRecipe {
    if (isExpertPanel) {
      return {
        size: Math.max(1, selectedPersonas.length),
        dist: {},
        locale: "local",
      }
    }
    return {
      size: effectiveSize,
      dist,
      locale: "local",
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

  async function createExpertPanel() {
    if (selectedPersonas.length === 0) {
      setLoadError(t("expertPanels.builder.noExpertsSelected"))
      return
    }
    setSubmitting(true)
    setLoadError(null)
    const name = popName.trim() || t("expertPanels.builder.fallbackName")
    try {
      const panel = await createPopulation({
        kind: "expert_panel",
        name,
        recipe: buildRecipe(),
        include_persona_ids: selectedIds,
      })
      navigate(`${basePath}/${panel.id}`)
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : t("expertPanels.builder.createError"),
      )
    } finally {
      setSubmitting(false)
    }
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
          include_persona_ids: selectedIds,
          kind,
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
    if (cur < maxStep) {
      setCur(cur + 1)
      setMaxReached((m) => Math.max(m, cur + 1))
    }
  }

  function back() {
    if (cur > 1) setCur(cur - 1)
  }

  const libraryStep = isExpertPanel ? 2 : 3
  const distributionsStep = 2

  return (
    <Shell>
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

        {cur === 1 && (
          <section>
            <div className="section-head">
              <span className="kicker">
                {t(isExpertPanel ? "expertPanels.builder.step1Kicker" : "populations.builder.step1Kicker")}
              </span>
              <h1
                style={{
                  font: "var(--text-h1)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                }}
              >
                {t(isExpertPanel ? "expertPanels.builder.step1Title" : "populations.builder.step1Title")}
              </h1>
              <p>{t(isExpertPanel ? "expertPanels.builder.step1Body" : "populations.builder.step1Body")}</p>
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="pop-name">
                  {t(isExpertPanel ? "expertPanels.builder.nameLabel" : "populations.builder.nameLabel")}
                </label>
                <input
                  id="pop-name"
                  value={popName}
                  onChange={(e) => setPopName(e.target.value)}
                />
              </div>
              {!isExpertPanel ? (
                <div className="field">
                  <label htmlFor="pop-size">{t("populations.builder.sizeLabel")}</label>
                  <input
                    id="pop-size"
                    type="number"
                    min={4}
                    max={100}
                    value={popSize}
                    onChange={(e) => setPopSize(parseInt(e.target.value, 10) || 12)}
                  />
                </div>
              ) : null}
            </div>
          </section>
        )}

        {!isExpertPanel && cur === distributionsStep && (
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
                {isAdmin ? (
                  <Link to="/tools/configurations" style={{ color: "var(--db-gold-700)" }}>
                    {t("populations.builder.configLink")}
                  </Link>
                ) : (
                  t("populations.builder.configName")
                )}
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

        {cur === libraryStep && (
          <section>
            <div className="section-head">
              <span className="kicker">
                {t(
                  isExpertPanel
                    ? "expertPanels.builder.step2Kicker"
                    : "populations.builder.step3Kicker",
                )}
              </span>
              <h1
                style={{
                  font: "var(--text-h1)",
                  fontFamily: "'Bai Jamjuree', sans-serif",
                  fontWeight: 400,
                }}
              >
                {t(
                  isExpertPanel
                    ? "expertPanels.builder.step2Title"
                    : "populations.builder.step3Title",
                )}
              </h1>
              <p>
                {t(
                  isExpertPanel
                    ? "expertPanels.builder.step2Body"
                    : "populations.builder.step3Body",
                )}
              </p>
            </div>
            {!isExpertPanel ? (
              <div className="prev-grid">
                {Object.keys(dist).map((gkey) => (
                  <PrevGroup key={gkey} group={dist[gkey]!} />
                ))}
              </div>
            ) : null}

            <div style={{ marginTop: 28, marginBottom: 10 }}>
              <h3 style={{ font: "var(--text-h3)", marginBottom: 6 }}>
                {t(
                  isExpertPanel
                    ? "expertPanels.builder.expertsTitle"
                    : "populations.builder.libraryTitle",
                )}
              </h3>
              {!isExpertPanel ? (
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
              ) : (
                <p style={{ color: "var(--text-muted)", fontSize: 13.5, marginBottom: 12 }}>
                  {t("expertPanels.builder.expertsSummary", { count: libraryCount })}
                </p>
              )}
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
                            {isExpertPanel
                              ? p.occ
                              : `${p.age} · ${p.occ} · ${p.district}`}
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
                personaKind={personaKind}
                excludeIds={selectedIds}
                onAdd={addLibraryPersona}
                hint={t(
                  isExpertPanel
                    ? "expertPanels.builder.expertsHint"
                    : "populations.builder.libraryHint",
                )}
              />
            </div>

            <div className="run-cta">
              <AdminButton
                variant="accent"
                disabled={submitting || (isExpertPanel && selectedPersonas.length === 0)}
                onClick={() => void (isExpertPanel ? createExpertPanel() : startGenerationJob())}
              >
                {submitting
                  ? t(
                      isExpertPanel
                        ? "expertPanels.builder.creating"
                        : "populations.builder.startingJob",
                    )
                  : isExpertPanel
                    ? t("expertPanels.builder.createPanel")
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
          {cur !== maxStep && (
            <AdminButton variant="primary" onClick={next}>
              {t("common.next")}
            </AdminButton>
          )}
        </div>
      </div>
    </Shell>
  )
}
