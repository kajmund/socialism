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
import { ApiError } from "@/lib/api"

const STEP_TITLES = ["Starta", "Fördelningar", "Förhandsgranska"] as const
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
const CATALOG_DIST_MAP: { catalogKey: string; groupKey: string; fallbackLabel: string }[] = [
  { catalogKey: "ort", groupKey: "district", fallbackLabel: "Distrikt" },
  { catalogKey: "yrke", groupKey: "occupation", fallbackLabel: "Yrken" },
  { catalogKey: "utbildning", groupKey: "education", fallbackLabel: "Utbildningsnivåer" },
  { catalogKey: "livssituation", groupKey: "livssituation", fallbackLabel: "Livssituationer" },
  { catalogKey: "lutning", groupKey: "leaning", fallbackLabel: "Politisk lutning" },
  { catalogKey: "parti", groupKey: "parti", fallbackLabel: "Partisympatier" },
  { catalogKey: "valdeltagande", groupKey: "valdeltagande", fallbackLabel: "Valdeltagande" },
  { catalogKey: "sakfragor", groupKey: "sakfragor", fallbackLabel: "Sakfrågor" },
  { catalogKey: "fortroende", groupKey: "fortroende", fallbackLabel: "Förtroende" },
  { catalogKey: "ton", groupKey: "ton", fallbackLabel: "Ton" },
  { catalogKey: "sprak", groupKey: "sprak", fallbackLabel: "Språkmönster" },
  { catalogKey: "medievanor", groupKey: "media", fallbackLabel: "Medievanor" },
]

function mergeMissingDist(base: DistState, extras: DistState): DistState {
  const next: DistState = { ...base }
  for (const [key, group] of Object.entries(extras)) {
    if (!(key in next)) next[key] = group
  }
  return next
}

const AGE_GROUP: DistGroupData = {
  label: "Åldersspann",
  rows: [
    { k: "ung", l: "Ung (18–34)", v: 30 },
    { k: "medel", l: "Medel (35–59)", v: 45 },
    { k: "aldre", l: "Äldre (60+)", v: 25 },
  ],
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

function distFromCatalog(lists: CatalogList[]): DistState {
  const byKey = new Map(lists.map((list) => [list.key, list]))
  const dist: DistState = {
    age: { label: AGE_GROUP.label, rows: AGE_GROUP.rows.map((r) => ({ ...r })) },
  }
  for (const { catalogKey, groupKey, fallbackLabel } of CATALOG_DIST_MAP) {
    const list = byKey.get(catalogKey)
    const labels = (list?.items ?? [])
      .map((item) => item.label.trim())
      .filter(Boolean)
    if (labels.length === 0) continue
    dist[groupKey] = {
      label: list?.title || fallbackLabel,
      rows: equalWeightRows(labels),
    }
  }
  return dist
}

function normalizeGroup(rows: DistRow[]) {
  const sum = rows.reduce((a, r) => a + r.v, 0) || 1
  rows.forEach((r) => {
    r.v = Math.round((r.v * 100) / sum)
  })
  let diff = 100 - rows.reduce((a, r) => a + r.v, 0)
  rows[0]!.v += diff
  return rows
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
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const editId = id && id !== "new" ? Number(id) : null
  const isEditRecipe = !!editId || params.get("edit") === "1"

  const [cur, setCur] = useState(isEditRecipe ? 2 : 1)
  const [maxReached, setMaxReached] = useState(isEditRecipe ? 3 : 1)
  const [entryMode, setEntryMode] = useState<"free" | "manual">("free")
  const [freeText, setFreeText] = useState(
    "En blandad grupp, något höger-tung, cynisk ton",
  )
  const [popName, setPopName] = useState("Ny population")
  const [popSize, setPopSize] = useState(12)
  const [dist, setDist] = useState<DistState>(() => ({
    age: { label: AGE_GROUP.label, rows: AGE_GROUP.rows.map((r) => ({ ...r })) },
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

  useEffect(() => {
    let cancelled = false
    listCatalog()
      .then((lists) => {
        if (cancelled) return
        const fromCatalog = distFromCatalog(lists)
        if (!editId) setDist(fromCatalog)
        else setDist((prev) => mergeMissingDist(prev, fromCatalog))
        setCatalogReady(true)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(
            err instanceof ApiError ? err.message : "Kunde inte hämta konfiguration",
          )
          setCatalogReady(true)
        }
      })
    return () => {
      cancelled = true
    }
  }, [editId])

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
        if (pop.recipe && typeof pop.recipe === "object" && "entryMode" in pop.recipe) {
          const mode = pop.recipe.entryMode
          if (mode === "free" || mode === "manual") setEntryMode(mode)
        }
        if (pop.recipe && typeof pop.recipe === "object" && "freeText" in pop.recipe) {
          const text = pop.recipe.freeText
          if (typeof text === "string") setFreeText(text)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setLoadError(err instanceof ApiError ? err.message : "Kunde inte hämta population")
        }
      })
    return () => {
      cancelled = true
    }
  }, [editId])

  function buildRecipe(): PopulationRecipe {
    return {
      size: effectiveSize,
      entryMode,
      freeText,
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

  function applyFreeTextHeuristics() {
    if (entryMode !== "free" || !freeText) return
    const txt = freeText.toLowerCase()
    setDist((prev) => {
      const next = JSON.parse(JSON.stringify(prev)) as DistState
      const skew = (
        gkey: string,
        up: (r: DistRow) => boolean,
        down: (r: DistRow) => boolean,
      ) => {
        const group = next[gkey]
        if (!group) return
        group.rows.forEach((r) => {
          if (up(r)) r.v = Math.round(r.v * 1.6)
          if (down(r)) r.v = Math.round(r.v * 0.5)
        })
        normalizeGroup(group.rows)
      }
      const labelHas = (needle: string) => (r: DistRow) =>
        r.l.toLowerCase().includes(needle) ||
        r.k.includes(needle.replace(/[äå]/g, "a").replace(/ö/g, "o"))
      if (txt.includes("höger")) {
        skew("leaning", labelHas("höger"), labelHas("vänster"))
      }
      if (txt.includes("vänster")) {
        skew("leaning", labelHas("vänster"), labelHas("höger"))
      }
      if (txt.includes("äldre") || txt.includes("pensionär")) {
        skew("age", (r) => r.k === "aldre", (r) => r.k === "ung")
      }
      if (txt.includes("ung")) {
        skew("age", (r) => r.k === "ung", (r) => r.k === "aldre")
      }
      return next
    })
  }

  async function startGenerationJob() {
    setSubmitting(true)
    setLoadError(null)
    const name = popName.trim() || "Namnlös population"
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
        err instanceof ApiError ? err.message : "Kunde inte starta bakgrundsjobb",
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
    if (cur === 1) applyFreeTextHeuristics()
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
          {STEP_TITLES.map((t, i) => {
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
                <div className="step-t">{t}</div>
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
            Redigerar recept för »{popName}« — generering sparas som en ny version.
          </div>
        )}

        {cur === 1 && (
          <section>
            <div className="section-head">
              <span className="kicker">Steg 1 · Starta</span>
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Hur vill du starta populationen?
              </h1>
              <p>
                Beskriv gruppen i ord, eller ställ in demografiska fördelningar själv.
                Generering körs som bakgrundsjobb.
              </p>
            </div>
            <div className="entry-grid entry-grid-2">
              <button
                type="button"
                className={"entry-card" + (entryMode === "free" ? " sel" : "")}
                onClick={() => setEntryMode("free")}
              >
                <Card className="gap-0 py-5 ring-1 ring-border">
                  <CardContent className="px-5">
                    <h3 style={{ font: "var(--text-h3)", marginBottom: 8 }}>
                      Fritextbeskrivning
                    </h3>
                    <p style={{ color: "var(--text-muted)", fontSize: 13.5 }}>
                      Skriv en kort beskrivning — vi föreslår demografiska fördelningar du kan
                      justera i nästa steg.
                    </p>
                    {entryMode === "free" && (
                      <textarea
                        className="free"
                        value={freeText}
                        onChange={(e) => setFreeText(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    )}
                  </CardContent>
                </Card>
              </button>
              <button
                type="button"
                className={"entry-card" + (entryMode === "manual" ? " sel" : "")}
                onClick={() => setEntryMode("manual")}
              >
                <Card className="gap-0 py-5 ring-1 ring-border">
                  <CardContent className="px-5">
                    <h3 style={{ font: "var(--text-h3)", marginBottom: 8 }}>Bygg manuellt</h3>
                    <p style={{ color: "var(--text-muted)", fontSize: 13.5 }}>
                      Hoppa över fritext — gå direkt till fördelningarna med neutrala
                      standardvärden och justera själv.
                    </p>
                  </CardContent>
                </Card>
              </button>
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="pop-name">Populationens namn</label>
                <input
                  id="pop-name"
                  value={popName}
                  onChange={(e) => setPopName(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="pop-size">Önskad storlek (personas)</label>
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
              <span className="kicker">Steg 2 · Fördelningar</span>
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Ställ in demografiska fördelningar
              </h1>
              <p>
                Justera reglagen per dimension. Alternativen kommer från{" "}
                <Link to="/config" style={{ color: "var(--db-gold-700)" }}>
                  Konfiguration
                </Link>
                . Balansen normaliseras automatiskt till 100%.
              </p>
            </div>
            {!catalogReady ? (
              <div className="no-match" style={{ textAlign: "left" }}>
                Hämtar konfiguration…
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
              <span className="kicker">Steg 3 · Förhandsgranska</span>
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Så här ser populationen ut i sin helhet
              </h1>
              <p>
                Välj gärna personas från biblioteket. Resten genereras upp till önskad
                storlek — eller skapa enbart med bibliotekspicks.
              </p>
            </div>
            <div className="prev-grid">
              {Object.keys(dist).map((gkey) => (
                <PrevGroup key={gkey} group={dist[gkey]!} />
              ))}
            </div>

            <div style={{ marginTop: 28, marginBottom: 10 }}>
              <h3 style={{ font: "var(--text-h3)", marginBottom: 6 }}>
                Från biblioteket
              </h3>
              <p style={{ color: "var(--text-muted)", fontSize: 13.5, marginBottom: 12 }}>
                {libraryCount} från bibliotek · {generateCount} genereras
                {effectiveSize !== popSize
                  ? ` · storlek höjd till ${effectiveSize}`
                  : ` · storlek ${effectiveSize}`}
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
                        Ta bort
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <AddFromLibraryPanel
                excludeIds={selectedIds}
                onAdd={addLibraryPersona}
                hint="Lägg till personas från biblioteket. Du kan skapa populationen med bara dessa, eller fylla på med genererade."
              />
            </div>

            <div className="run-cta">
              <AdminButton
                variant="accent"
                disabled={submitting}
                onClick={() => void startGenerationJob()}
              >
                {submitting
                  ? "Startar jobb…"
                  : generateCount === 0
                    ? "Skapa population →"
                    : "Generera personas →"}
              </AdminButton>
            </div>
          </section>
        )}

        <div className="nav-bar">
          <AdminButton variant="secondary" disabled={cur === 1} onClick={back}>
            ← Tillbaka
          </AdminButton>
          {cur !== 3 && (
            <AdminButton variant="primary" onClick={next}>
              Nästa →
            </AdminButton>
          )}
        </div>
      </div>
    </AdminShell>
  )
}
