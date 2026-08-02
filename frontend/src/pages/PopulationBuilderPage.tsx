import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { createPersona, editableToWrite } from "@/api/personas"
import {
  createPopulation,
  generatePopulation,
  getPopulation,
  updatePopulation,
  type GenerationCandidate,
  type PopulationRecipe,
} from "@/api/populations"
import { AdminShell } from "@/components/layout/AdminShell"
import { AddFromLibraryPanel } from "@/components/populations/AddFromLibraryPanel"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { personaInitials } from "@/data/library"
import { ApiError } from "@/lib/api"

const STEP_TITLES = ["Starta", "Fördelningar", "Förhandsgranska", "Generera", "Spara"] as const
const ROW_COLORS = [
  "var(--db-ink-950)",
  "var(--db-gold-500)",
  "var(--db-ink-600)",
  "var(--db-gold-300)",
  "var(--db-ink-400)",
  "var(--db-ink-200)",
]

type DistRow = { k: string; l: string; v: number }
type DistGroupData = { label: string; rows: DistRow[] }
type DistState = Record<string, DistGroupData>

const DIST_INIT: DistState = {
  age: {
    label: "Åldersspann",
    rows: [
      { k: "ung", l: "Ung (18–34)", v: 30 },
      { k: "medel", l: "Medel (35–59)", v: 45 },
      { k: "aldre", l: "Äldre (60+)", v: 25 },
    ],
  },
  district: {
    label: "Stadsdel / ort",
    rows: [
      { k: "hageby", l: "Distrikt A", v: 18 },
      { k: "navestad", l: "Distrikt B", v: 16 },
      { k: "lindo", l: "Distrikt C", v: 14 },
      { k: "klockaretorpet", l: "Distrikt D", v: 16 },
      { k: "centrum", l: "Centrum", v: 20 },
      { k: "ovriga", l: "Övriga", v: 16 },
    ],
  },
  occupation: {
    label: "Yrkeskategori",
    rows: [
      { k: "vard", l: "Vård & omsorg", v: 20 },
      { k: "industri", l: "Industri / logistik", v: 22 },
      { k: "utbildning", l: "Utbildning", v: 10 },
      { k: "handel", l: "Handel / service", v: 18 },
      { k: "tjansteman", l: "Tjänstemän", v: 14 },
      { k: "ovrigt", l: "Arbetslös / pension", v: 16 },
    ],
  },
  education: {
    label: "Utbildningsnivå",
    rows: [
      { k: "grund", l: "Grundskola", v: 22 },
      { k: "gymn", l: "Gymnasium", v: 48 },
      { k: "hogsk", l: "Högskola / universitet", v: 30 },
    ],
  },
  leaning: {
    label: "Politisk lutning",
    rows: [
      { k: "vanster", l: "Vänster", v: 14 },
      { k: "mvanster", l: "Mitt-vänster", v: 16 },
      { k: "mitt", l: "Mitt", v: 20 },
      { k: "mhoger", l: "Mitt-höger", v: 24 },
      { k: "hoger", l: "Höger", v: 26 },
    ],
  },
  media: {
    label: "Medievanor / kanaler",
    rows: [
      { k: "nt", l: "Lokal nyhetskälla", v: 24 },
      { k: "svtost", l: "Regional TV", v: 18 },
      { k: "fb", l: "Facebook-grupper", v: 22 },
      { k: "ig", l: "Instagram / TikTok", v: 20 },
      { k: "ingen", l: "Lite / ingen media", v: 16 },
    ],
  },
}

const LEAN_LABEL: Record<string, string> = {
  vanster: "Vänster",
  mvanster: "Mitt-vänster",
  mitt: "Mitt",
  mhoger: "Mitt-höger",
  hoger: "Höger",
}

type BatchPersona = {
  key: string
  name: string
  initials: string
  age: number
  district: string
  districtKey: string
  occ: string
  occKey: string
  lean: string
  trait: string
  savedToLibrary?: boolean
  fromLibrary?: boolean
  libraryId?: string
  profile?: GenerationCandidate["persona"]["profile"]
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

function candidateToBatch(c: GenerationCandidate): BatchPersona {
  return {
    key: c.key,
    name: c.persona.name,
    initials: c.persona.initials,
    age: c.persona.age,
    district: c.persona.district,
    districtKey: c.persona.district_key,
    occ: c.persona.occ,
    occKey: c.persona.occ_key,
    lean: c.persona.lean,
    trait: c.persona.trait,
    fromLibrary: c.source === "library",
    savedToLibrary: c.source === "library" || !!c.persona_id,
    libraryId: c.persona_id ?? undefined,
    profile: c.persona.profile,
  }
}

function batchToCandidate(p: BatchPersona): GenerationCandidate {
  return {
    key: p.key,
    source: p.fromLibrary ? "library" : "generated",
    persona_id: p.libraryId ?? null,
    persona: {
      name: p.name,
      initials: p.initials,
      age: p.age,
      occ: p.occ,
      district: p.district,
      occ_key: p.occKey,
      district_key: p.districtKey,
      lean: p.lean,
      lean_label: LEAN_LABEL[p.lean] ?? p.lean,
      trait: p.trait,
      quote: p.trait,
      profile: p.profile ?? {
        name: p.name,
        initials: p.initials,
        age: String(p.age),
        ort: p.district,
        yrke: p.occ,
        utbildning: "—",
        livssituation: "—",
        lutning: LEAN_LABEL[p.lean] ?? p.lean,
        sakfragor: "—",
        fortroende: "—",
        ton: p.trait,
        sprak: "—",
        medievanor: "—",
        parti: "—",
        valdeltagande: "—",
      },
    },
  }
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
        {group.rows.map((r, i) => (
          <div className="dist-row" key={r.k}>
            <div
              className="dot"
              style={{ background: ROW_COLORS[i % ROW_COLORS.length] }}
            />
            <div>
              <div className="lbl">{r.l}</div>
              <input
                type="range"
                min={0}
                max={100}
                value={r.v}
                onChange={(e) => onSlide(gkey, r.k, parseInt(e.target.value, 10))}
              />
            </div>
            <div className="pct">{r.v}%</div>
          </div>
        ))}
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
  const [maxReached, setMaxReached] = useState(isEditRecipe ? 5 : 1)
  const [entryMode, setEntryMode] = useState<"free" | "manual">("free")
  const [freeText, setFreeText] = useState(
    "En blandad grupp, något höger-tung, cynisk ton",
  )
  const [popName, setPopName] = useState("Ny population")
  const [popSize, setPopSize] = useState(12)
  const [dist, setDist] = useState<DistState>(() =>
    JSON.parse(JSON.stringify(DIST_INIT)) as DistState,
  )
  const [batch, setBatch] = useState<BatchPersona[]>([])
  const [generationId, setGenerationId] = useState<string | null>(null)
  const [savedToast, setSavedToast] = useState(false)
  const [showAddExisting, setShowAddExisting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!editId) return
    let cancelled = false
    getPopulation(editId)
      .then((pop) => {
        if (cancelled) return
        setPopName(pop.name)
        setPopSize(pop.size || pop.members.length || 12)
        if (pop.recipe && typeof pop.recipe === "object" && "dist" in pop.recipe) {
          setDist(pop.recipe.dist as DistState)
        }
        if (pop.recipe && typeof pop.recipe === "object" && "entryMode" in pop.recipe) {
          const mode = pop.recipe.entryMode
          if (mode === "free" || mode === "manual") setEntryMode(mode)
        }
        if (pop.recipe && typeof pop.recipe === "object" && "freeText" in pop.recipe) {
          const text = pop.recipe.freeText
          if (typeof text === "string") setFreeText(text)
        }
        setBatch(
          pop.members.map((m) => ({
            key: `mem_${m.id ?? Math.random().toString(36).slice(2)}`,
            name: m.name,
            initials: m.initials,
            age: m.age,
            district: m.district,
            districtKey: "",
            occ: m.occ,
            occKey: "",
            lean: "mitt",
            trait: m.trait,
            savedToLibrary: !!m.id,
            fromLibrary: !!m.id,
            libraryId: m.id,
          })),
        )
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

  const libraryCount = batch.filter((p) => p.fromLibrary).length
  const generatedCount = batch.length - libraryCount

  function buildRecipe(): PopulationRecipe {
    return {
      size: popSize,
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
      const skew = (gkey: string, up: string[], down: string[]) => {
        const group = next[gkey]
        if (!group) return
        group.rows.forEach((r) => {
          if (up.includes(r.k)) r.v = Math.round(r.v * 1.6)
          if (down.includes(r.k)) r.v = Math.round(r.v * 0.5)
        })
        normalizeGroup(group.rows)
      }
      if (txt.includes("höger")) skew("leaning", ["hoger", "mhoger"], ["vanster", "mvanster"])
      if (txt.includes("vänster")) skew("leaning", ["vanster", "mvanster"], ["hoger", "mhoger"])
      if (txt.includes("äldre") || txt.includes("pensionär")) skew("age", ["aldre"], ["ung"])
      if (txt.includes("ung")) skew("age", ["ung"], ["aldre"])
      return next
    })
  }

  function addFromLibrary(p: {
    id: string
    name: string
    age: number
    quote: string
    occ: string
    district: string
  }) {
    setBatch((b) => [
      ...b,
      {
        key: `lib_${p.id}_${Math.random().toString(36).slice(2, 8)}`,
        name: p.name,
        initials: personaInitials(p.name),
        age: p.age,
        district: p.district,
        districtKey: "",
        occ: p.occ,
        occKey: "",
        lean: "mitt",
        trait: p.quote,
        savedToLibrary: true,
        fromLibrary: true,
        libraryId: p.id,
      },
    ])
  }

  async function saveBatchPersonaToLibrary(i: number) {
    const p = batch[i]
    if (!p || p.fromLibrary || p.savedToLibrary) return
    const editable = p.profile ?? {
      name: p.name,
      initials: p.initials,
      age: String(p.age),
      ort: p.district,
      yrke: p.occ,
      utbildning: "—",
      livssituation: "—",
      lutning: LEAN_LABEL[p.lean] ?? p.lean,
      sakfragor: "—",
      fortroende: "—",
      ton: p.trait,
      sprak: "—",
      medievanor: "—",
      parti: "—",
      valdeltagande: "—",
    }
    try {
      const saved = await createPersona(
        editableToWrite(editable, "population", p.trait),
      )
      setBatch((b) =>
        b.map((x, idx) =>
          idx === i ? { ...x, savedToLibrary: true, libraryId: saved.id } : x,
        ),
      )
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Kunde inte spara persona")
    }
  }

  async function savePopulation() {
    if (batch.length === 0) return
    setSaving(true)
    setLoadError(null)
    try {
      const libraryMembers = batch
        .filter((p) => p.fromLibrary && p.libraryId)
        .map((p) => ({
          persona_id: p.libraryId,
          name: p.name,
          initials: p.initials,
          age: p.age,
          occ: p.occ,
          district: p.district,
          trait: p.trait,
        }))

      if (generationId) {
        const payload = {
          name: popName || "Namnlös population",
          generation_id: generationId,
          keep_keys: batch.map((p) => p.key),
          members: libraryMembers,
          recipe: buildRecipe(),
        }
        if (editId) {
          await updatePopulation(editId, { ...payload, bump_version: true })
        } else {
          await createPopulation(payload)
        }
      } else {
        const members = []
        for (const p of batch) {
          let personaId = p.libraryId
          if (!personaId && !p.fromLibrary) {
            const editable = p.profile ?? {
              name: p.name,
              initials: p.initials,
              age: String(p.age),
              ort: p.district,
              yrke: p.occ,
              utbildning: "—",
              livssituation: "—",
              lutning: LEAN_LABEL[p.lean] ?? p.lean,
              sakfragor: "—",
              fortroende: "—",
              ton: p.trait,
              sprak: "—",
              medievanor: "—",
              parti: "—",
              valdeltagande: "—",
            }
            const created = await createPersona(
              editableToWrite(editable, "population", p.trait),
            )
            personaId = created.id
          }
          members.push({
            persona_id: personaId,
            name: p.name,
            initials: p.initials,
            age: p.age,
            occ: p.occ,
            district: p.district,
            trait: p.trait,
          })
        }
        const payload = {
          name: popName || "Namnlös population",
          recipe: buildRecipe(),
          members,
        }
        if (editId) {
          await updatePopulation(editId, { ...payload, bump_version: true })
        } else {
          await createPopulation(payload)
        }
      }
      setSavedToast(true)
      window.setTimeout(() => navigate("/populations"), 900)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Kunde inte spara population")
    } finally {
      setSaving(false)
    }
  }

  async function generateBatch(mode: "replace" | "append" = "replace") {
    setGenerating(true)
    setLoadError(null)
    try {
      const result = await generatePopulation({
        recipe: buildRecipe(),
        generation_id: generationId,
        existing: batch.map(batchToCandidate),
        mode,
      })
      setGenerationId(result.generation_id)
      setBatch(result.candidates.map(candidateToBatch))
      setCur(4)
      setMaxReached((m) => Math.max(m, 4))
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Kunde inte generera personas")
    } finally {
      setGenerating(false)
    }
  }

  async function regenPersona(key: string) {
    setGenerating(true)
    setLoadError(null)
    try {
      const result = await generatePopulation({
        recipe: buildRecipe(),
        generation_id: generationId,
        existing: batch.map(batchToCandidate),
        replace_keys: [key],
      })
      setGenerationId(result.generation_id)
      setBatch(result.candidates.map(candidateToBatch))
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Kunde inte regenerera persona")
    } finally {
      setGenerating(false)
    }
  }

  function next() {
    if (cur === 1) applyFreeTextHeuristics()
    if (cur < 5) {
      setCur(cur + 1)
      setMaxReached((m) => Math.max(m, cur + 1))
    }
  }

  function back() {
    if (cur > 1) setCur(cur - 1)
  }

  function entryMeta() {
    const base =
      entryMode === "manual"
        ? "Byggd manuellt"
        : "Skapad från fritextbeskrivning"
    return libraryCount > 0 ? `${base} + tillagda från bibliotek` : base
  }

  const leanCounts: Record<string, number> = {}
  batch.forEach((p) => {
    leanCounts[p.lean] = (leanCounts[p.lean] || 0) + 1
  })
  const total = batch.length || 1

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
            Redigerar recept för »{popName}« — sparas som en ny version.
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
                Personas från biblioteket kan läggas till efter generering.
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
                Justera reglagen per dimension. Balansen normaliseras automatiskt till 100%.
              </p>
            </div>
            <div className="dist-grid">
              {Object.keys(dist).map((gkey) => (
                <DistGroup key={gkey} gkey={gkey} group={dist[gkey]!} onSlide={onSlide} />
              ))}
            </div>
          </section>
        )}

        {cur === 3 && (
          <section>
            <div className="section-head">
              <span className="kicker">Steg 3 · Förhandsgranska</span>
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Så här ser populationen ut i sin helhet
              </h1>
              <p>Kontrollera den aggregerade sammansättningen innan personas genereras.</p>
            </div>
            <div className="prev-grid">
              {Object.keys(dist).map((gkey) => (
                <PrevGroup key={gkey} group={dist[gkey]!} />
              ))}
            </div>
            <div className="run-cta">
              <AdminButton
                variant="accent"
                disabled={generating}
                onClick={() => void generateBatch(batch.length ? "append" : "replace")}
              >
                {generating
                  ? "Genererar…"
                  : batch.length
                    ? `Generera ${Math.max(1, popSize - batch.length)} till →`
                    : "Generera personas →"}
              </AdminButton>
            </div>
          </section>
        )}

        {cur === 4 && (
          <section>
            <div className="section-head">
              <span className="kicker">Steg 4 · Generera & granska</span>
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Granska batchen
              </h1>
              <p>
                Regenerera, kasta, lägg till från biblioteket, eller öppna en persona.
              </p>
            </div>
            <div className="batch-summary">
              <div className="bs-item">
                <b>{batch.length}</b> av mål <b>{popSize}</b> personas
              </div>
              <div className="bs-item">
                Bibliotek: <b>{libraryCount}</b>
              </div>
              <div className="bs-item">
                Genererade: <b>{generatedCount}</b>
              </div>
              {Object.keys(LEAN_LABEL).map((k) => {
                const targetRow = dist.leaning.rows.find((r) => r.k === k)
                const target = targetRow?.v ?? 0
                const actual = Math.round(((leanCounts[k] || 0) * 100) / total)
                const diff = Math.abs(actual - target)
                return (
                  <div className="bs-item" key={k}>
                    {LEAN_LABEL[k]}: mål <b>{target}%</b> → faktiskt{" "}
                    <b className={diff <= 8 ? "ok" : "warn"}>{actual}%</b>
                  </div>
                )
              })}
            </div>
            <div className="compose-actions">
              <div className="compose-actions-left">
                <AdminButton
                  variant="accent"
                  disabled={generating}
                  onClick={() => void generateBatch(batch.length ? "append" : "replace")}
                >
                  {generating
                    ? "Genererar…"
                    : batch.length
                      ? `+ Generera ${Math.max(1, popSize - batch.length)} till`
                      : "Generera personas"}
                </AdminButton>
              </div>
              <button
                type="button"
                className="add-lib-toggle"
                onClick={() => setShowAddExisting((v) => !v)}
              >
                {showAddExisting
                  ? "Dölj bibliotek ←"
                  : "+ Lägg till från bibliotek →"}
              </button>
            </div>
            {showAddExisting && (
              <AddFromLibraryPanel
                excludeNames={batch.map((p) => p.name)}
                hint="Lägg till en befintlig persona från biblioteket i den här batchen."
                onAdd={addFromLibrary}
              />
            )}
            {batch.length === 0 ? (
              <div className="no-match" style={{ textAlign: "left", padding: "12px 0 24px" }}>
                Ingen batch ännu. Generera personas, eller lägg till från biblioteket.
              </div>
            ) : (
              <div className="pcard-grid">
                {batch.map((p, i) => (
                  <div className="pcard" key={p.key}>
                    <Card className="h-full gap-0 py-4 ring-1 ring-border">
                      <CardContent className="pcard-inner px-4">
                        <div className="ph">
                          <div className="av">{p.initials}</div>
                          <div style={{ minWidth: 0 }}>
                            <div className="nm">{p.name}</div>
                            <div className="meta">
                              {p.fromLibrary
                                ? `${p.age} · från bibliotek`
                                : `${p.age} · ${p.occ} · ${p.district}`}
                            </div>
                          </div>
                        </div>
                        <div className="trait">
                          {p.trait}
                        </div>
                        <div style={{ fontSize: 10.5, color: "var(--text-muted)", fontStyle: "italic" }}>
                          {p.fromLibrary || p.savedToLibrary ? (
                            <span style={{ color: "var(--db-success)", fontStyle: "normal" }}>
                              ✓ Sparad i bibliotek
                            </span>
                          ) : (
                            "Ny — ej sparad"
                          )}
                        </div>
                        <div className="actions">
                          {!p.fromLibrary && (
                            <button
                              type="button"
                              disabled={generating}
                              onClick={() => void regenPersona(p.key)}
                            >
                              ↻ Regen.
                            </button>
                          )}
                          <button
                            type="button"
                            className="discard"
                            onClick={() =>
                              setBatch((b) => b.filter((_, idx) => idx !== i))
                            }
                          >
                            ✕ Kasta
                          </button>
                          <Link
                            to={p.libraryId ? `/personas/${p.libraryId}` : "/personas/new"}
                          >
                            Öppna →
                          </Link>
                          {!p.fromLibrary && (
                            <button
                              type="button"
                              disabled={p.savedToLibrary}
                              onClick={() => void saveBatchPersonaToLibrary(i)}
                            >
                              💾 Spara
                            </button>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {cur === 5 && (
          <section>
            <div className="section-head">
              <span className="kicker">Steg 5 · Spara</span>
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Bekräfta och spara population
              </h1>
            </div>
            <div className="confirm-card">
              <Card className="gap-0 ring-1 ring-border" style={{ padding: 0 }}>
                <div className="inner">
                  <div style={{ font: "var(--text-label)", color: "var(--text-muted)" }}>
                    Population
                  </div>
                  <div className="n">{popName || "Namnlös population"}</div>
                  <div className="meta">{entryMeta()}</div>
                  <div className="rows">
                    <div>
                      <div className="v">{batch.length}</div>
                      <div className="l">Personas</div>
                    </div>
                    <div>
                      <div className="v">{libraryCount}</div>
                      <div className="l">Från bibliotek</div>
                    </div>
                    <div>
                      <div className="v">{generatedCount}</div>
                      <div className="l">Genererade</div>
                    </div>
                  </div>
                  <AdminButton
                    variant="primary"
                    style={{ width: "100%", padding: 14 }}
                    disabled={batch.length === 0 || saving}
                    onClick={() => void savePopulation()}
                  >
                    Spara & gå till Populationer
                  </AdminButton>
                </div>
              </Card>
            </div>
          </section>
        )}

        <div className="nav-bar">
          <AdminButton
            variant="secondary"
            disabled={cur === 1}
            onClick={back}
          >
            ← Tillbaka
          </AdminButton>
          {cur !== 3 && cur !== 5 && (
            <AdminButton
              variant="primary"
              onClick={next}
              disabled={cur === 4 && batch.length === 0}
            >
              {cur === 4 ? "Fortsätt till spara →" : "Nästa →"}
            </AdminButton>
          )}
        </div>
      </div>
      {savedToast && (
        <div className="toast">
          <div className="ck">✓</div>
          Population sparad
        </div>
      )}
    </AdminShell>
  )
}
