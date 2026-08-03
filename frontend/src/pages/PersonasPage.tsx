import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"
import {
  catalogToFieldOptions,
  listCatalog,
} from "@/api/catalog"
import { deletePersona, listPersonas, updatePersona } from "@/api/personas"
import { AdminShell } from "@/components/layout/AdminShell"
import {
  PersonaCardFields,
  type CardFieldKey,
} from "@/components/personas/PersonaCardFields"
import { Card, CardContent } from "@/components/ui/card"
import { blankEditablePersona, formatLibraryDate, ORIGIN_LABEL, personaInitials } from "@/data/library"
import type { EditablePersona, LibraryPersona, PersonaOrigin } from "@/data/library-types"
import { ApiError } from "@/lib/api"

function DiagramExplainer() {
  return (
    <Card className="mb-6 gap-0 py-6 ring-1 ring-border">
      <CardContent className="px-6">
        <div
          style={{
            font: "var(--text-label)",
            color: "var(--text-muted)",
            marginBottom: 14,
          }}
        >
          En persona kan höra till flera populationer, en, eller ingen —
          biblioteket är alltid platt.
        </div>
        <svg
          viewBox="0 0 560 190"
          style={{ width: "100%", maxWidth: 560, height: "auto" }}
          role="img"
        >
          <title>Personas kan tillhöra flera populationer eller vara ofördelade</title>
          <rect x="30" y="14" width="200" height="46" rx="23" fill="var(--db-ink-950)" />
          <text
            x="130"
            y="42"
            textAnchor="middle"
            fill="var(--db-ink-0)"
            fontSize="13"
          >
            Baslinjepopulation
          </text>
          <rect x="330" y="14" width="200" height="46" rx="23" fill="var(--db-gold-500)" />
          <text
            x="430"
            y="42"
            textAnchor="middle"
            fill="var(--db-navy-ink)"
            fontSize="13"
          >
            Kärnväljare
          </text>
          <line x1="110" y1="60" x2="110" y2="150" stroke="var(--db-ink-400)" strokeWidth="1.5" />
          <line x1="110" y1="150" x2="430" y2="60" stroke="var(--db-ink-400)" strokeWidth="1.5" />
          <line x1="230" y1="150" x2="150" y2="60" stroke="var(--db-ink-400)" strokeWidth="1.5" />
          <line x1="350" y1="150" x2="430" y2="60" stroke="var(--db-ink-400)" strokeWidth="1.5" />
          {(
            [
              [110, "MH"],
              [230, "HY"],
              [350, "EL"],
              [470, "BK"],
            ] as const
          ).map(([cx, label]) => (
            <g key={cx}>
              <circle
                cx={cx}
                cy="150"
                r="20"
                fill="var(--db-ink-100)"
                stroke="var(--db-ink-950)"
                strokeWidth="1.5"
              />
              <text x={cx} y="155" textAnchor="middle" fontSize="11" fontWeight="600">
                {label}
              </text>
            </g>
          ))}
          <text
            x="470"
            y="185"
            textAnchor="middle"
            fontSize="10"
            fill="var(--text-muted)"
            fontStyle="italic"
          >
            Ofördelad
          </text>
        </svg>
      </CardContent>
    </Card>
  )
}

type SaveStatus = "idle" | "saving" | "saved" | "error"

function ensureProfile(persona: LibraryPersona): EditablePersona {
  return persona.profile ?? {
    ...blankEditablePersona(),
    name: persona.name,
    initials: personaInitials(persona.name),
    age: String(persona.age),
    yrke: persona.occ,
    ort: persona.district,
  }
}

function applyProfileField(
  persona: LibraryPersona,
  key: CardFieldKey,
  value: string,
): LibraryPersona {
  const profile = { ...ensureProfile(persona), [key]: value }
  let age = persona.age
  let occ = persona.occ
  let district = persona.district
  let quote = persona.quote
  if (key === "age") {
    const parsed = Number.parseInt(value, 10)
    if (Number.isFinite(parsed)) age = parsed
  }
  if (key === "yrke") occ = value
  if (key === "ort") district = value
  // List view short description uses quote; composer treats ton as the source.
  if (key === "ton") quote = value
  return { ...persona, age, occ, district, quote, profile }
}

type PersonaCardProps = {
  persona: LibraryPersona
  open: boolean
  fieldOptions: Record<string, string[]>
  saveStatus: SaveStatus
  onTogglePops: () => void
  onFieldChange: (key: CardFieldKey, value: string) => void
  onDelete: (id: string) => void
}

function PersonaCard({
  persona,
  open,
  fieldOptions,
  saveStatus,
  onTogglePops,
  onFieldChange,
  onDelete,
}: PersonaCardProps) {
  const [confirming, setConfirming] = useState(false)
  const profile = ensureProfile(persona)
  const statusLabel =
    saveStatus === "saving"
      ? "Sparar…"
      : saveStatus === "saved"
        ? "Sparad"
        : saveStatus === "error"
          ? "Kunde inte spara"
          : `Uppdaterad ${formatLibraryDate(persona.updated)}`

  return (
    <div className="p-card">
      <Card className="h-full gap-0 py-4 ring-1 ring-border">
        <CardContent className="p-inner px-4">
          <div className="p-headrow">
            <div className="av">{personaInitials(persona.name)}</div>
            <div>
              <div className="nm" style={{ fontSize: "0.95rem" }}>
                {persona.name}
              </div>
            </div>
          </div>
          <PersonaCardFields
            profile={profile}
            fieldOptions={fieldOptions}
            onChange={onFieldChange}
          />
          <div className="tag-row">
            {persona.pops.length === 0 ? (
              <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
                Ofördelad
              </span>
            ) : (
              <button
                type="button"
                className="affil-btn"
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onTogglePops()
                }}
              >
                <span className="rounded-full bg-db-gold-100 px-2 py-0.5 text-[11px] font-semibold text-db-gold-700">
                  I {persona.pops.length} population
                  {persona.pops.length > 1 ? "er" : ""}
                </span>
                {open && (
                  <div className="affil-pop">
                    {persona.pops.map((n) => (
                      <div key={n}>· {n}</div>
                    ))}
                  </div>
                )}
              </button>
            )}
            <span className="rounded-full border border-[color:var(--border-hairline)] px-2 py-0.5 text-[11px]">
              {ORIGIN_LABEL[persona.origin]}
            </span>
          </div>
          <div
            className={
              "updated" +
              (saveStatus === "error" ? " is-error" : "") +
              (saveStatus === "saved" || saveStatus === "saving" ? " is-live" : "")
            }
          >
            {statusLabel}
          </div>
          {confirming ? (
            <div className="confirm-row" style={{ marginTop: 0 }}>
              <button type="button" style={{ flex: 1 }} onClick={() => setConfirming(false)}>
                Avbryt
              </button>
              <button
                type="button"
                className="yes"
                style={{ flex: 1 }}
                onClick={() => onDelete(persona.id)}
              >
                Ta bort?
              </button>
            </div>
          ) : (
            <div className="card-actions">
              <Link className="primary" to={`/personas/${persona.id}`}>
                Öppna
              </Link>
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

function PersonaRow({
  persona,
  open,
  onTogglePops,
  onDelete,
}: Omit<PersonaCardProps, "fieldOptions" | "saveStatus" | "onFieldChange">) {
  const [confirming, setConfirming] = useState(false)
  const affilText =
    persona.pops.length === 0 ? "Ofördelad" : `I ${persona.pops.length} pop.`
  return (
    <div className="p-row">
      <Link
        to={`/personas/${persona.id}`}
        style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0, color: "inherit", textDecoration: "none" }}
      >
        <div className="av" style={{ width: 28, height: 28, fontSize: 11 }}>
          {personaInitials(persona.name)}
        </div>
        <div className="nm2">{persona.name}</div>
      </Link>
      <div className="quote2">
        {persona.quote || ensureProfile(persona).ton || "—"}
      </div>
      <div className="meta">
        {persona.age} · {persona.occ} · {persona.district}
      </div>
      {persona.pops.length === 0 ? (
        <div
          style={{
            fontSize: 11.5,
            fontWeight: 700,
            color: "var(--text-muted)",
          }}
        >
          {affilText}
        </div>
      ) : (
        <button
          type="button"
          className="affil-btn"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onTogglePops()
          }}
          style={{
            fontSize: 11.5,
            fontWeight: 700,
            color: "var(--db-gold-700)",
            textAlign: "left",
          }}
        >
          {affilText}
          {open && (
            <div className="affil-pop" style={{ top: 20 }}>
              {persona.pops.map((n) => (
                <div key={n}>· {n}</div>
              ))}
            </div>
          )}
        </button>
      )}
      <div style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "right" }}>
        {ORIGIN_LABEL[persona.origin]}
      </div>
      {confirming ? (
        <div className="confirm-row" style={{ gap: 6 }}>
          <button type="button" onClick={() => setConfirming(false)}>
            Avbryt
          </button>
          <button type="button" className="yes" onClick={() => onDelete(persona.id)}>
            Ta bort?
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="danger"
          style={{
            fontSize: 11.5,
            border: "1px solid var(--border-hairline)",
            borderRadius: "var(--radius-sm)",
            background: "var(--db-ink-0)",
            cursor: "pointer",
            padding: "6px 8px",
          }}
          onClick={() => setConfirming(true)}
        >
          Ta bort
        </button>
      )}
    </div>
  )
}

export function PersonasPage() {
  const [personas, setPersonas] = useState<LibraryPersona[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fieldOptions, setFieldOptions] = useState<Record<string, string[]>>({})
  const [view, setView] = useState<"grid" | "lista">("grid")
  const [query, setQuery] = useState("")
  const [affil, setAffil] = useState("alla")
  const [origin, setOrigin] = useState<"alla" | PersonaOrigin>("alla")
  const [sort, setSort] = useState<"updated" | "name" | "pops">("updated")
  const [popOpenIdx, setPopOpenIdx] = useState(-1)
  const [showDiagram, setShowDiagram] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [saveStatus, setSaveStatus] = useState<Record<string, SaveStatus>>({})
  const pendingRef = useRef<Record<string, LibraryPersona>>({})
  const timersRef = useRef<Record<string, number>>({})
  const savedFlashRef = useRef<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([listPersonas(), listCatalog()])
      .then(([data, catalog]) => {
        if (!cancelled) {
          setPersonas(data)
          setFieldOptions(catalogToFieldOptions(catalog))
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Kunde inte hämta personas")
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const h = () => setPopOpenIdx(-1)
    document.addEventListener("click", h)
    return () => document.removeEventListener("click", h)
  }, [])

  useEffect(() => {
    const timers = timersRef.current
    const flashes = savedFlashRef.current
    return () => {
      for (const id of Object.keys(timers)) window.clearTimeout(timers[id])
      for (const id of Object.keys(flashes)) window.clearTimeout(flashes[id])
    }
  }, [])

  const popNames = useMemo(() => {
    const names = new Set<string>()
    for (const p of personas) for (const name of p.pops) names.add(name)
    return [...names].sort((a, b) => a.localeCompare(b, "sv"))
  }, [personas])

  const list = useMemo(() => {
    let next = personas.filter((p) => {
      const ql = query.toLowerCase()
      const matchQ =
        !ql ||
        p.name.toLowerCase().includes(ql) ||
        p.district.toLowerCase().includes(ql) ||
        p.occ.toLowerCase().includes(ql)
      const matchAffil =
        affil === "alla" ||
        (affil === "fristaende" ? p.pops.length === 0 : p.pops.includes(affil))
      const matchOrigin = origin === "alla" || p.origin === origin
      return matchQ && matchAffil && matchOrigin
    })
    if (sort === "name") next = [...next].sort((a, b) => a.name.localeCompare(b.name, "sv"))
    if (sort === "pops") next = [...next].sort((a, b) => b.pops.length - a.pops.length)
    if (sort === "updated") {
      next = [...next].sort(
        (a, b) => new Date(b.updated).getTime() - new Date(a.updated).getTime(),
      )
    }
    return next
  }, [personas, query, affil, origin, sort])

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(null), 2400)
  }

  function markSaved(id: string) {
    setSaveStatus((prev) => ({ ...prev, [id]: "saved" }))
    window.clearTimeout(savedFlashRef.current[id])
    savedFlashRef.current[id] = window.setTimeout(() => {
      setSaveStatus((prev) => (prev[id] === "saved" ? { ...prev, [id]: "idle" } : prev))
    }, 1600)
  }

  async function persistPersona(id: string) {
    const body = pendingRef.current[id]
    if (!body) return
    delete pendingRef.current[id]
    setSaveStatus((prev) => ({ ...prev, [id]: "saving" }))
    try {
      const saved = await updatePersona(id, {
        name: body.name,
        age: body.age,
        occ: body.occ,
        district: body.district,
        quote: body.quote,
        origin: body.origin,
        profile: ensureProfile(body),
      })
      setPersonas((prev) =>
        prev.map((p) => {
          if (p.id !== id) return p
          if (pendingRef.current[id]) return p
          return {
            ...p,
            age: saved.age,
            occ: saved.occ,
            district: saved.district,
            quote: saved.quote,
            updated: saved.updated,
            profile: saved.profile,
          }
        }),
      )
      markSaved(id)
    } catch (err) {
      setSaveStatus((prev) => ({ ...prev, [id]: "error" }))
      showToast(err instanceof ApiError ? err.message : "Kunde inte spara")
    }
  }

  function schedulePersist(persona: LibraryPersona, immediate: boolean) {
    pendingRef.current[persona.id] = persona
    window.clearTimeout(timersRef.current[persona.id])
    if (immediate) {
      void persistPersona(persona.id)
      return
    }
    timersRef.current[persona.id] = window.setTimeout(() => {
      void persistPersona(persona.id)
    }, 450)
  }

  function handleFieldChange(id: string, key: CardFieldKey, value: string) {
    let nextPersona: LibraryPersona | null = null
    setPersonas((prev) =>
      prev.map((p) => {
        if (p.id !== id) return p
        nextPersona = applyProfileField(p, key, value)
        return nextPersona
      }),
    )
    if (nextPersona) schedulePersist(nextPersona, key !== "age")
  }

  async function handleDelete(id: string) {
    try {
      await deletePersona(id)
      window.clearTimeout(timersRef.current[id])
      delete pendingRef.current[id]
      setPersonas((prev) => prev.filter((p) => p.id !== id))
      showToast("Persona borttagen")
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte ta bort")
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
              Personas
            </h1>
            <div
              style={{
                font: "var(--text-body-sm)",
                color: "var(--text-muted)",
                marginTop: 6,
                maxWidth: 640,
              }}
            >
              Alla skapade personas i ett platt bibliotek — oavsett om de tillhör
              en population eller är fristående. Ändra fält direkt på kortet; det
              sparas automatiskt.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowDiagram(!showDiagram)}
            style={{
              background: "none",
              border: "none",
              textDecoration: "underline",
              color: "var(--text-muted)",
              fontSize: 12.5,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            {showDiagram ? "Dölj förklaring" : "Hur funkar det?"}
          </button>
        </div>

        {showDiagram && <DiagramExplainer />}

        <div className="controls-row">
          <div className="controls-left">
            <input
              className="dsearch"
              placeholder="Sök namn, ort, yrke..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select className="dsel" value={affil} onChange={(e) => setAffil(e.target.value)}>
              <option value="alla">Alla</option>
              <option value="fristaende">Fristående</option>
              {popNames.map((name) => (
                <option key={name} value={name}>
                  Tillhör: {name}
                </option>
              ))}
            </select>
            <select
              className="dsel"
              value={origin}
              onChange={(e) => setOrigin(e.target.value as "alla" | PersonaOrigin)}
            >
              <option value="alla">Alla ursprung</option>
              <option value="manuell">Manuell</option>
              <option value="beskrivning">Från beskrivning</option>
              <option value="demografi">Från demografi</option>
              <option value="population">Genererad via population</option>
            </select>
            <select
              className="dsel"
              value={sort}
              onChange={(e) => setSort(e.target.value as "updated" | "name" | "pops")}
            >
              <option value="updated">Sortera: Senast uppdaterad</option>
              <option value="name">Sortera: Namn</option>
              <option value="pops">Sortera: Antal populationer</option>
            </select>
          </div>
          <Link
            to="/personas/new"
            className="admin-cta inline-flex h-9 items-center rounded-md bg-db-black px-4 text-sm text-db-ink-0 no-underline hover:bg-db-ink-800"
          >
            + Ny persona
          </Link>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
          <div className="view-toggle">
            <button
              type="button"
              className={view === "grid" ? "on" : ""}
              onClick={() => setView("grid")}
            >
              ⬚ Rutnät
            </button>
            <button
              type="button"
              className={view === "lista" ? "on" : ""}
              onClick={() => setView("lista")}
            >
              ≡ Lista
            </button>
          </div>
        </div>

        {error && (
          <div className="no-match" style={{ textAlign: "left", marginBottom: 16 }}>
            {error}
          </div>
        )}

        {loading ? (
          <div className="no-match">Hämtar personas…</div>
        ) : view === "grid" ? (
          <div className="p-grid persona-grid">
            {list.length ? (
              list.map((p, i) => (
                <PersonaCard
                  key={p.id}
                  persona={p}
                  open={popOpenIdx === i}
                  fieldOptions={fieldOptions}
                  saveStatus={saveStatus[p.id] ?? "idle"}
                  onTogglePops={() => setPopOpenIdx(popOpenIdx === i ? -1 : i)}
                  onFieldChange={(key, value) => handleFieldChange(p.id, key, value)}
                  onDelete={handleDelete}
                />
              ))
            ) : (
              <div className="no-match">Inga personas matchar filtren.</div>
            )}
          </div>
        ) : (
          <div className="p-list">
            {list.length ? (
              list.map((p, i) => (
                <PersonaRow
                  key={p.id}
                  persona={p}
                  open={popOpenIdx === i}
                  onTogglePops={() => setPopOpenIdx(popOpenIdx === i ? -1 : i)}
                  onDelete={handleDelete}
                />
              ))
            ) : (
              <div className="no-match">Inga personas matchar filtren.</div>
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
