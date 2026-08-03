import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import {
  catalogToFieldOptions,
  listCatalog,
} from "@/api/catalog"
import {
  chatWithPersona,
  clearPersonaMessages,
  createPersona,
  deletePersona,
  duplicatePersona,
  editableToWrite,
  generatePersonas,
  getPersona,
  listPersonaMessages,
  updatePersona,
  type ChatMode,
  type PersonaMessage,
} from "@/api/personas"
import { AdminShell } from "@/components/layout/AdminShell"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { blankEditablePersona } from "@/data/library"
import type { EditablePersona, PersonaOrigin } from "@/data/library-types"
import { ApiError } from "@/lib/api"

type LayerRow = { k: keyof EditablePersona | string; l: string; v: string; locked: boolean }

type LayerTableProps = {
  rows: LayerRow[]
  pol?: boolean
  fieldOptions: Record<string, string[]>
  onChange: (k: string, v?: string) => void
}

function LayerTable({ rows, pol, fieldOptions, onChange }: LayerTableProps) {
  return (
    <table className={"lt" + (pol ? " pol" : "")}>
      <tbody>
        {rows.map((r) => {
          const opts = fieldOptions[r.k]
          // Lock marks fields for regeneration — it must not block editing.
          const cell =
            opts && opts.length > 0 ? (
              <select
                className="cell-input"
                value={r.v}
                onChange={(e) => onChange(r.k, e.target.value)}
              >
                {!opts.includes(r.v) && (
                  <option value={r.v}>{r.v || "—"}</option>
                )}
                {opts.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="cell-input"
                value={r.v}
                onChange={(e) => onChange(r.k, e.target.value)}
              />
            )
          return (
            <tr key={r.k}>
              <td className="k">{r.l}</td>
              <td>{cell}</td>
              <td className="lk">
                <span
                  className={"lock" + (r.locked ? " on" : "")}
                  onClick={() => onChange("__lock__" + r.k)}
                  title={
                    r.locked
                      ? "Låst vid regenerering"
                      : "Olåst — kan ändras vid regenerering"
                  }
                >
                  {r.locked ? "🔒" : "🔓"}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Drawer({ persona }: { persona: EditablePersona }) {
  const [open, setOpen] = useState(true)
  return (
    <div className={"drawer" + (open ? "" : " collapsed")}>
      <div className="drawer-head" onClick={() => setOpen(!open)}>
        <div className="t">▾ system_prompt.txt — live</div>
        <div className="n">~{300 + persona.name.length * 3} tok</div>
      </div>
      <div className="drawer-body">
        Du är {persona.name}, {persona.age}, {persona.yrke}, boende i {persona.ort}...
        <br />
        <b>[LÅST]</b> Politisk lutning: {persona.lutning}. Partisympati: {persona.parti}...
        <br />
        Ton: {persona.ton}.
      </div>
    </div>
  )
}

type EditorProps = {
  persona: EditablePersona
  personaId: string | null
  setPersona: (updater: (p: EditablePersona) => EditablePersona) => void
  onOpenVariants: () => void
  onDuplicate: () => void
  onSave: () => void
  onDelete?: () => void
  onToast: (message: string) => void
  fieldOptions: Record<string, string[]>
  saving?: boolean
  deleting?: boolean
}

function Editor({
  persona,
  personaId,
  setPersona,
  onOpenVariants,
  onDuplicate,
  onSave,
  onDelete,
  onToast,
  fieldOptions,
  saving,
  deleting,
}: EditorProps) {
  const [mode, setMode] = useState<"work" | "present">("work")
  const [icMode, setIcMode] = useState<ChatMode>("interview")
  const [saved, setSaved] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [locks, setLocks] = useState<Record<string, boolean>>({
    age: true,
    ort: true,
    lutning: true,
    parti: true,
    valdeltagande: true,
  })
  const [messages, setMessages] = useState<PersonaMessage[]>([])
  const [draft, setDraft] = useState("")
  const [chatBusy, setChatBusy] = useState(false)

  useEffect(() => {
    if (!personaId) {
      setMessages([])
      return
    }
    let cancelled = false
    listPersonaMessages(personaId, icMode)
      .then((rows) => {
        if (!cancelled) setMessages(rows)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          onToast(err instanceof ApiError ? err.message : "Kunde inte hämta chatt")
        }
      })
    return () => {
      cancelled = true
    }
    // intentionally omit onToast — parent recreates it each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personaId, icMode])

  async function sendMessage(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !personaId || chatBusy) return
    setChatBusy(true)
    try {
      const result = await chatWithPersona(personaId, { mode: icMode, message: trimmed })
      setMessages(result.messages)
      setDraft("")
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : "Kunde inte skicka")
    } finally {
      setChatBusy(false)
    }
  }

  async function regenerate() {
    if (!personaId || chatBusy) return
    const lastUser = [...messages].reverse().find((m) => m.role === "user")
    setChatBusy(true)
    try {
      await clearPersonaMessages(personaId, icMode)
      if (lastUser) {
        const result = await chatWithPersona(personaId, {
          mode: icMode,
          message: lastUser.content,
        })
        setMessages(result.messages)
      } else {
        setMessages([])
      }
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : "Kunde inte regenerera")
    } finally {
      setChatBusy(false)
    }
  }

  function upd(k: string, v?: string) {
    if (k.startsWith("__lock__")) {
      const field = k.slice("__lock__".length)
      setLocks((prev) => ({ ...prev, [field]: !prev[field] }))
      return
    }
    setPersona((p) => {
      const next = { ...p, [k]: v ?? "" }
      if (k === "name") {
        const parts = next.name.split(" ")
        next.initials = (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")
        next.initials = next.initials.toUpperCase() || "--"
      }
      return next
    })
  }

  return (
    <>
      <div className="topbar">
        <div className="persona-id">
          <div className="avatar">{persona.initials}</div>
          <div>
            <input
              className="nm-input"
              value={persona.name}
              onChange={(e) => upd("name", e.target.value)}
            />
            <div className="sub">
              {persona.age} · {persona.yrke} · {persona.ort}
            </div>
          </div>
        </div>
        <div className="topbar-actions">
          <div className="mode-switch">
            <button
              type="button"
              className={mode === "work" ? "on" : ""}
              onClick={() => setMode("work")}
            >
              Arbetsläge
            </button>
            <button
              type="button"
              className={mode === "present" ? "on" : ""}
              onClick={() => setMode("present")}
            >
              Presentationsläge
            </button>
          </div>
          <AdminButton variant="secondary" size="sm" onClick={onDuplicate}>
            Duplicera
          </AdminButton>
          <AdminButton variant="secondary" size="sm" onClick={onOpenVariants}>
            Varianter ×5
          </AdminButton>
          <AdminButton
            variant="primary"
            size="sm"
            disabled={saving || deleting}
            onClick={() => {
              onSave()
              setSaved(true)
              window.setTimeout(() => setSaved(false), 2600)
            }}
          >
            Spara persona
          </AdminButton>
          {onDelete &&
            (confirmDelete ? (
              <>
                <AdminButton
                  variant="secondary"
                  size="sm"
                  disabled={deleting}
                  onClick={() => setConfirmDelete(false)}
                >
                  Avbryt
                </AdminButton>
                <AdminButton
                  variant="secondary"
                  size="sm"
                  disabled={deleting}
                  onClick={onDelete}
                >
                  Bekräfta borttagning
                </AdminButton>
              </>
            ) : (
              <AdminButton
                variant="secondary"
                size="sm"
                disabled={deleting}
                onClick={() => setConfirmDelete(true)}
              >
                Ta bort
              </AdminButton>
            ))}
          <Link to="/personas/new" className="no-underline">
            <AdminButton variant="secondary" size="sm">
              + Ny persona
            </AdminButton>
          </Link>
        </div>
      </div>
      {saved && (
        <div className="toast">
          <div className="ck">✓</div>Persona sparad i biblioteket
        </div>
      )}

      <div className="work" style={{ display: mode === "work" ? "flex" : "none" }}>
        <div className="layers-col">
          <div className="layer-h">I. Demografi</div>
          <LayerTable
            fieldOptions={fieldOptions}
            onChange={upd}
            rows={[
              { k: "age", l: "Ålder", v: persona.age, locked: !!locks.age },
              { k: "kön", l: "Kön", v: persona.kön, locked: !!locks.kön },
              { k: "ort", l: "Distrikt", v: persona.ort, locked: !!locks.ort },
              { k: "yrke", l: "Yrke", v: persona.yrke, locked: !!locks.yrke },
              { k: "utbildning", l: "Utbildning", v: persona.utbildning, locked: !!locks.utbildning },
              { k: "livssituation", l: "Livssituation", v: persona.livssituation, locked: !!locks.livssituation },
            ]}
          />
          <div className="layer-h">II. Värderingar & attityder</div>
          <LayerTable
            fieldOptions={fieldOptions}
            onChange={upd}
            rows={[
              { k: "lutning", l: "Lutning", v: persona.lutning, locked: !!locks.lutning },
              { k: "sakfragor", l: "Sakfrågor", v: persona.sakfragor, locked: !!locks.sakfragor },
              { k: "fortroende", l: "Förtroende", v: persona.fortroende, locked: !!locks.fortroende },
            ]}
          />
          <div className="layer-h">III. Röst & personlighet</div>
          <LayerTable
            fieldOptions={fieldOptions}
            onChange={upd}
            rows={[
              { k: "ton", l: "Ton", v: persona.ton, locked: !!locks.ton },
              { k: "sprak", l: "Språkmönster", v: persona.sprak, locked: !!locks.sprak },
              { k: "medievanor", l: "Medievanor", v: persona.medievanor, locked: !!locks.medievanor },
            ]}
          />
          <div className="layer-h pol">IV. Domänänattribut · Politik</div>
          <LayerTable
            pol
            fieldOptions={fieldOptions}
            onChange={upd}
            rows={[
              { k: "parti", l: "Partisympati", v: persona.parti, locked: !!locks.parti },
              { k: "valdeltagande", l: "Valdeltagande", v: persona.valdeltagande, locked: !!locks.valdeltagande },
            ]}
          />
        </div>
        <div className="chat-col">
          <div className="chat-top">
            <div className="ic-switch">
              <button
                type="button"
                className={icMode === "character" ? "on" : ""}
                onClick={() => setIcMode("character")}
              >
                In-character
              </button>
              <button
                type="button"
                className={icMode === "interview" ? "on" : ""}
                onClick={() => setIcMode("interview")}
              >
                Intervju
              </button>
            </div>
            <AdminButton
              variant="secondary"
              size="sm"
              disabled={!personaId || chatBusy || messages.length === 0}
              onClick={() => void regenerate()}
            >
              ↻ Regenerera svar
            </AdminButton>
          </div>
          <div className="chat-msgs">
            {!personaId && (
              <div className="bub them">Spara personan för att börja intervjua.</div>
            )}
            {personaId && messages.length === 0 && (
              <div className="bub them">Ställ en fråga för att börja samtalet.</div>
            )}
            {messages.map((m) => (
              <div
                key={m.id}
                className={"bub " + (m.role === "assistant" ? "them" : "me")}
              >
                {m.content}
              </div>
            ))}
          </div>
          <div className="chat-input">
            <input
              placeholder={personaId ? "Meddelande..." : "Spara persona först"}
              value={draft}
              disabled={!personaId || chatBusy}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  void sendMessage(draft)
                }
              }}
            />
            <AdminButton
              variant="primary"
              size="sm"
              disabled={!personaId || chatBusy || !draft.trim()}
              onClick={() => void sendMessage(draft)}
            >
              {chatBusy ? "…" : "Skicka"}
            </AdminButton>
          </div>
        </div>
      </div>
      {mode === "work" && <Drawer persona={persona} />}

      <div className={"present" + (mode === "present" ? " show" : "")}>
        <div className="p-portrait-col">
          <div
            className="flex h-[260px] w-full items-center justify-center rounded bg-db-ink-100 text-sm text-[color:var(--text-muted)]"
          >
            Porträtt av {persona.name}
          </div>
          <h1 className="p-name" style={{ fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
            {persona.name}
          </h1>
          <div className="p-tag">
            {persona.age} år, {persona.yrke}, {persona.ort} — {persona.parti}
          </div>
          <div className="p-sec">
            <div className="p-num">I.</div>
            <div className="p-lbl">Demografi</div>
            <p>
              {persona.name} bor i <b>{persona.ort}</b> ({persona.livssituation}) och arbetar
              som <b>{persona.yrke}</b> med utbildningsnivå {persona.utbildning}.
            </p>
          </div>
          <div className="p-sec">
            <div className="p-num">II.</div>
            <div className="p-lbl">Värderingar</div>
            <p>
              Politiskt lutar personen <b>{persona.lutning}</b>. Engagemang kring{" "}
              {persona.sakfragor}. Förtroende: {persona.fortroende}.
            </p>
          </div>
          <div className="p-sec">
            <div className="p-num">III.</div>
            <div className="p-lbl">Röst & personlighet</div>
            <p>
              Ton: <b>{persona.ton}</b>. Språkmönster: {persona.sprak}. Medievanor:{" "}
              {persona.medievanor}.
            </p>
          </div>
          <div className="p-sec pol">
            <div className="p-num">IV.</div>
            <div className="p-lbl">Politik</div>
            <p>
              Partisympati: <b>{persona.parti}</b>. Valdeltagande:{" "}
              <b>{persona.valdeltagande}</b>.
            </p>
          </div>
        </div>
        <div className="p-interview">
          <div className="p-interview-head">
            <h3 style={{ fontStyle: "italic", fontSize: 22 }}>Intervju</h3>
          </div>
          <div className="p-transcript">
            {!personaId && (
              <p>
                <i>Spara personan för att intervjua.</i>
              </p>
            )}
            {personaId && messages.length === 0 && (
              <p>
                <i>Ingen intervju ännu.</i>
              </p>
            )}
            {messages.map((m) => (
              <p key={m.id}>
                {m.role === "assistant" ? (
                  <>
                    <b>{persona.initials}:</b> {m.content}
                  </>
                ) : (
                  <>
                    <b style={{ color: "var(--db-gold-700)" }}>Du:</b>{" "}
                    <i>{m.content}</i>
                  </>
                )}
              </p>
            ))}
          </div>
          <div
            className="chat-input"
            style={{ borderTop: "1px solid var(--border-hairline)", paddingTop: 16, marginTop: 4 }}
          >
            <input
              placeholder={"Fråga " + persona.name + " något..."}
              value={draft}
              disabled={!personaId || chatBusy}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  void sendMessage(draft)
                }
              }}
            />
            <AdminButton
              variant="primary"
              size="sm"
              disabled={!personaId || chatBusy || !draft.trim()}
              onClick={() => void sendMessage(draft)}
            >
              {chatBusy ? "…" : "Skicka"}
            </AdminButton>
          </div>
        </div>
      </div>
    </>
  )
}

export function PersonaComposerPage() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const startCreating = params.get("new") === "1" || id === "new"
  const existingId = !startCreating && id && id !== "new" ? id : null

  const [screen, setScreen] = useState<"create" | "edit" | "variants">(
    startCreating ? "create" : "edit",
  )
  const [createStep, setCreateStep] = useState<"choose" | "free" | "demografi" | "candidates">(
    "choose",
  )
  const [createOrigin, setCreateOrigin] = useState<PersonaOrigin>("manuell")
  const [candidates, setCandidates] = useState<EditablePersona[]>([])
  const [toast, setToast] = useState("")
  const [persona, setPersona] = useState<EditablePersona | null>(
    startCreating ? null : blankEditablePersona(),
  )
  const [personaId, setPersonaId] = useState<string | null>(existingId)
  const [loading, setLoading] = useState(!!existingId)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [freeText, setFreeText] = useState(
    "45-årig undersköterska, S-sympatisör men trött på partiet, sarkastisk",
  )
  const [demo, setDemo] = useState({
    age: "42",
    kön: "Kvinna",
    ort: "Distrikt A",
    yrke: "Handläggare",
    utbildning: "Högskola",
    livssituation: "Sambo, barn",
  })
  const [generating, setGenerating] = useState(false)
  const [fieldOptions, setFieldOptions] = useState<Record<string, string[]>>({})

  function showToast(message: string) {
    setToast(message)
    window.setTimeout(() => setToast(""), 2400)
  }

  useEffect(() => {
    let cancelled = false
    listCatalog()
      .then((lists) => {
        if (!cancelled) setFieldOptions(catalogToFieldOptions(lists))
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          showToast(
            err instanceof ApiError ? err.message : "Kunde inte hämta grunddata",
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function runCandidateGenerate(
    mode: "beskrivning" | "demografi",
    count = 3,
  ) {
    setGenerating(true)
    try {
      const result = await generatePersonas({
        mode,
        freeText: mode === "beskrivning" ? freeText : "",
        demografi: mode === "demografi" ? demo : undefined,
        count,
      })
      setCandidates(
        result.candidates.map((c) => ({
          ...blankEditablePersona(),
          ...c,
          key: Math.random(),
        })),
      )
      setCreateStep("candidates")
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Kunde inte generera")
    } finally {
      setGenerating(false)
    }
  }

  useEffect(() => {
    if (!existingId) return
    let cancelled = false
    setLoading(true)
    getPersona(existingId)
      .then((detail) => {
        if (cancelled) return
        setPersona({ ...blankEditablePersona(), ...detail.profile })
        setPersonaId(detail.id)
        setCreateOrigin(detail.origin)
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setToast(err instanceof ApiError ? err.message : "Kunde inte hämta persona")
          window.setTimeout(() => setToast(""), 2400)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [existingId])

  function setPersonaState(updater: (p: EditablePersona) => EditablePersona) {
    setPersona((p) => (p ? updater(p) : p))
  }

  async function savePersona(target: EditablePersona, origin: PersonaOrigin) {
    setSaving(true)
    try {
      const body = editableToWrite(target, origin)
      if (personaId) {
        const saved = await updatePersona(personaId, body)
        setPersona({ ...blankEditablePersona(), ...saved.profile })
        setPersonaId(saved.id)
      } else {
        const saved = await createPersona(body)
        setPersona({ ...blankEditablePersona(), ...saved.profile })
        setPersonaId(saved.id)
        navigate(`/personas/${saved.id}`, { replace: true })
      }
    } catch (err) {
      setToast(err instanceof ApiError ? err.message : "Kunde inte spara")
      window.setTimeout(() => setToast(""), 2400)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <AdminShell>
        <div className="shell" style={{ height: "calc(100vh - 57px)" }}>
          <div className="mainarea">
            <div className="no-match">Hämtar persona…</div>
          </div>
        </div>
      </AdminShell>
    )
  }

  return (
    <AdminShell>
      <div className="shell" style={{ height: "calc(100vh - 57px)" }}>
        <div className="mainarea">
          {screen === "create" && createStep === "choose" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Skapa ny persona
              </h1>
              <p style={{ color: "var(--text-muted)", marginTop: 8, maxWidth: 600 }}>
                Välj hur du vill börja. Alla tre vägar landar i samma redigerbara persona.
              </p>
              <div className="entry-grid">
                {(
                  [
                    ["blank", "Tom", "Börja från en blank editor och fyll i allt själv.", "manuell"],
                    ["free", "Från beskrivning", "Skriv en kort text — vi genererar tre kandidater.", "beskrivning"],
                    ["demografi", "Från demografi", "Fyll i strukturerade fält — vi fyller i resten.", "demografi"],
                  ] as const
                ).map(([kind, title, desc, origin]) => (
                  <div
                    key={kind}
                    className="entry-card"
                    onClick={() => {
                      setCreateOrigin(origin)
                      if (kind === "blank") {
                        setPersona(blankEditablePersona())
                        setScreen("edit")
                      } else setCreateStep(kind)
                    }}
                  >
                    <Card className="gap-0 py-5 ring-1 ring-border">
                      <CardContent className="px-5">
                        <h3 style={{ font: "var(--text-h3)", marginBottom: 8 }}>{title}</h3>
                        <p style={{ color: "var(--text-muted)", fontSize: 13.5 }}>{desc}</p>
                      </CardContent>
                    </Card>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 24 }}>
                <AdminButton variant="secondary" onClick={() => navigate("/personas")}>
                  ← Tillbaka till biblioteket
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "create" && createStep === "free" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Beskriv personan
              </h1>
              <div className="field" style={{ marginTop: 20 }}>
                <label>Fritextbeskrivning</label>
                <textarea value={freeText} onChange={(e) => setFreeText(e.target.value)} />
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <AdminButton variant="secondary" onClick={() => setCreateStep("choose")}>
                  ← Tillbaka
                </AdminButton>
                <AdminButton
                  variant="primary"
                  disabled={generating}
                  onClick={() => void runCandidateGenerate("beskrivning")}
                >
                  {generating ? "Genererar…" : "Generera 3 kandidater →"}
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "create" && createStep === "demografi" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Demografiska fält
              </h1>
              <div className="form-grid" style={{ marginTop: 20 }}>
                {(
                  [
                    ["age", "Ålder"],
                    ["kön", "Kön"],
                    ["ort", "Distrikt"],
                    ["yrke", "Yrke"],
                    ["utbildning", "Utbildning"],
                    ["livssituation", "Livssituation"],
                  ] as const
                ).map(([k, label]) => {
                  const opts = fieldOptions[k]
                  return (
                    <div
                      className="field"
                      key={k}
                      style={k === "livssituation" ? { gridColumn: "1 / -1" } : undefined}
                    >
                      <label>{label}</label>
                      {opts && opts.length > 0 ? (
                        <select
                          className="dsearch"
                          value={demo[k]}
                          onChange={(e) => setDemo({ ...demo, [k]: e.target.value })}
                        >
                          {!opts.includes(demo[k]) && (
                            <option value={demo[k]}>{demo[k] || "—"}</option>
                          )}
                          {opts.map((o) => (
                            <option key={o} value={o}>
                              {o}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={demo[k]}
                          onChange={(e) => setDemo({ ...demo, [k]: e.target.value })}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <AdminButton variant="secondary" onClick={() => setCreateStep("choose")}>
                  ← Tillbaka
                </AdminButton>
                <AdminButton
                  variant="primary"
                  disabled={generating}
                  onClick={() => void runCandidateGenerate("demografi")}
                >
                  {generating ? "Genererar…" : "Generera 3 kandidater →"}
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "create" && createStep === "candidates" && (
            <div className="create-wrap">
              <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
                Välj en kandidat
              </h1>
              <p style={{ color: "var(--text-muted)", marginTop: 8 }}>
                Alla tre är genererade från samma indata. Du kan justera allt efteråt.
              </p>
              <div className="cand-grid">
                {candidates.map((c) => (
                  <div
                    className="cand-card"
                    key={c.key}
                    onClick={() => {
                      setPersona({ ...blankEditablePersona(), ...c })
                      setScreen("edit")
                    }}
                  >
                    <Card className="gap-0 py-5 ring-1 ring-border">
                      <CardContent className="px-5">
                        <div className="avatar" style={{ marginBottom: 10 }}>
                          {c.initials}
                        </div>
                        <div style={{ fontWeight: 700, fontSize: 15 }}>{c.name}</div>
                        <div
                          style={{
                            font: "var(--text-body-sm)",
                            color: "var(--text-muted)",
                            marginBottom: 10,
                          }}
                        >
                          {c.age} · {c.yrke} · {c.ort}
                        </div>
                        <div style={{ fontSize: 12.5, fontStyle: "italic" }}>{c.ton}</div>
                        <div
                          style={{
                            fontSize: 11.5,
                            color: "var(--db-gold-700)",
                            marginTop: 8,
                            fontWeight: 700,
                          }}
                        >
                          {c.lutning} · {c.parti}
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 24 }}>
                <AdminButton variant="secondary" onClick={() => setCreateStep("choose")}>
                  ← Tillbaka
                </AdminButton>
              </div>
            </div>
          )}

          {screen === "edit" && persona && (
            <Editor
              persona={persona}
              personaId={personaId}
              setPersona={setPersonaState}
              onOpenVariants={() => setScreen("variants")}
              onSave={() => {
                if (persona) void savePersona(persona, createOrigin)
              }}
              fieldOptions={fieldOptions}
              saving={saving}
              deleting={deleting}
              onToast={showToast}
              onDelete={
                personaId
                  ? () => {
                      void (async () => {
                        setDeleting(true)
                        try {
                          await deletePersona(personaId)
                          navigate("/personas")
                        } catch (err) {
                          setToast(
                            err instanceof ApiError ? err.message : "Kunde inte ta bort",
                          )
                          window.setTimeout(() => setToast(""), 2400)
                        } finally {
                          setDeleting(false)
                        }
                      })()
                    }
                  : undefined
              }
              onDuplicate={() => {
                if (personaId) {
                  void duplicatePersona(personaId)
                    .then((copy) => {
                      setToast("Persona duplicerad")
                      window.setTimeout(() => setToast(""), 2400)
                      navigate(`/personas/${copy.id}`)
                    })
                    .catch((err: unknown) => {
                      setToast(err instanceof ApiError ? err.message : "Kunde inte duplicera")
                      window.setTimeout(() => setToast(""), 2400)
                    })
                  return
                }
                setPersona((p) => (p ? { ...p, name: p.name + " (kopia)" } : p))
                setToast("Persona duplicerad")
                window.setTimeout(() => setToast(""), 2400)
              }}
            />
          )}

          {screen === "variants" && persona && (
            <VariantsView
              base={persona}
              origin={createOrigin}
              onDone={() => setScreen("edit")}
              onToast={showToast}
              onOpen={(c) => {
                setPersona(c)
                setPersonaId(null)
                setScreen("edit")
              }}
            />
          )}
        </div>
        {toast && (
          <div className="toast">
            <div className="ck">✓</div>
            {toast}
          </div>
        )}
      </div>
    </AdminShell>
  )
}

function VariantsView({
  base,
  origin,
  onDone,
  onOpen,
  onToast,
}: {
  base: EditablePersona
  origin: PersonaOrigin
  onDone: () => void
  onOpen: (c: EditablePersona) => void
  onToast: (message: string) => void
}) {
  const [variants, setVariants] = useState<EditablePersona[]>([])
  const [loading, setLoading] = useState(true)
  const [savedIdx, setSavedIdx] = useState<number[]>([])
  const [busyIdx, setBusyIdx] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    generatePersonas({
      mode: "demografi",
      demografi: {
        age: base.age,
        kön: base.kön,
        ort: base.ort,
        yrke: base.yrke,
        utbildning: base.utbildning,
        livssituation: base.livssituation,
      },
      freeText: `Varianter av ${base.name}, lutning ${base.lutning}, ton ${base.ton}`,
      count: 5,
    })
      .then((result) => {
        if (!cancelled) {
          setVariants(
            result.candidates.map((c) => ({
              ...blankEditablePersona(),
              ...c,
              key: Math.random(),
            })),
          )
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          onToast(err instanceof ApiError ? err.message : "Kunde inte generera varianter")
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base.name, base.age, base.kön, base.ort, base.yrke])

  async function saveVariant(i: number, c: EditablePersona) {
    setBusyIdx(i)
    try {
      await createPersona(editableToWrite(c, origin))
      setSavedIdx((s) => (s.includes(i) ? s : [...s, i]))
    } finally {
      setBusyIdx(null)
    }
  }

  return (
    <div className="create-wrap">
      <h1 style={{ font: "var(--text-h1)", fontFamily: "'Bai Jamjuree', sans-serif", fontWeight: 400 }}>
        5 varianter av {base.name}
      </h1>
      <p style={{ color: "var(--text-muted)", marginTop: 8, maxWidth: 640 }}>
        Samma profil, olika individer. Spara de du vill behålla i biblioteket.
      </p>
      {loading ? (
        <div className="no-match">Genererar varianter…</div>
      ) : (
      <div className="cand-grid">
        {variants.map((c, i) => (
          <div className="cand-card is-variant" key={c.key ?? i}>
            <Card className="gap-0 py-5 ring-1 ring-border">
              <CardContent className="px-5">
                <div className="avatar" style={{ marginBottom: 10 }}>
                  {c.initials}
                </div>
                <div style={{ fontWeight: 700, fontSize: 15 }}>{c.name}</div>
                <div
                  style={{
                    font: "var(--text-body-sm)",
                    color: "var(--text-muted)",
                    marginBottom: 10,
                  }}
                >
                  {c.age} · {c.yrke} · {c.ort}
                </div>
                <div style={{ fontSize: 12.5, fontStyle: "italic" }}>{c.ton}</div>
                <div
                  style={{
                    fontSize: 11.5,
                    color: "var(--db-gold-700)",
                    marginTop: 8,
                    marginBottom: 14,
                    fontWeight: 700,
                  }}
                >
                  {c.lutning} · {c.parti}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <AdminButton
                    variant={savedIdx.includes(i) ? "secondary" : "primary"}
                    size="sm"
                    style={{ flex: 1 }}
                    disabled={savedIdx.includes(i) || busyIdx === i}
                    onClick={() => void saveVariant(i, c)}
                  >
                    {savedIdx.includes(i) ? "✓ Sparad" : "Spara"}
                  </AdminButton>
                  <AdminButton
                    variant="secondary"
                    size="sm"
                    style={{ flex: 1 }}
                    onClick={() => onOpen(c)}
                  >
                    Öppna
                  </AdminButton>
                </div>
              </CardContent>
            </Card>
          </div>
        ))}
      </div>
      )}
      <div style={{ marginTop: 24, display: "flex", gap: 10, alignItems: "center" }}>
        <AdminButton variant="primary" onClick={onDone}>
          Klart — tillbaka till {base.name} →
        </AdminButton>
        <span style={{ font: "var(--text-body-sm)", color: "var(--text-muted)" }}>
          {savedIdx.length} av 5 sparade i biblioteket
        </span>
      </div>
    </div>
  )
}
