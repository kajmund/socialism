import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  libraryTypeForInjection,
  listMessages,
  type Message,
} from "@/api/messages"
import { MEASUREMENTS, makeInjection } from "@/data/runs"
import type { Injection, Tick } from "@/data/runs-types"

type RoundsDotsProps = {
  value: number
  onChange: (n: number) => void
}

export function RoundsDots({ value, onChange }: RoundsDotsProps) {
  return (
    <div style={{ display: "flex", alignItems: "center" }}>
      <div className="rounds-dots">
        {[0, 1, 2, 3, 4, 5].map((n) => (
          <button
            type="button"
            key={n}
            className={"rd-dot" + (n <= value ? " on" : "")}
            onClick={() => onChange(n)}
            title={n + " ronder"}
            aria-label={n + " ronder"}
            aria-pressed={n <= value}
          />
        ))}
      </div>
      <span className="rounds-num">
        {value} {value === 1 ? "rond" : "ronder"}
      </span>
    </div>
  )
}

type InjectionEditorProps = {
  inj: Injection
  onChange: (next: Injection) => void
  onRemove: () => void
}

export function InjectionEditor({ inj, onChange, onRemove }: InjectionEditorProps) {
  const typeId = `inj-type-${inj.key}`
  const senderId = `inj-sender-${inj.key}`
  const libraryId = `inj-lib-${inj.key}`
  const searchId = `inj-search-${inj.key}`
  const textId = `inj-text-${inj.key}`

  const libraryType = libraryTypeForInjection(inj.type)
  const [library, setLibrary] = useState<Message[]>([])
  const [libQuery, setLibQuery] = useState("")
  const [libError, setLibError] = useState<string | null>(null)
  const [scratchOpen, setScratchOpen] = useState(!inj.message_id && Boolean(inj.text))

  useEffect(() => {
    let cancelled = false
    listMessages({ type: libraryType })
      .then((data) => {
        if (!cancelled) {
          setLibrary(data)
          setLibError(null)
        }
      })
      .catch(() => {
        if (!cancelled) setLibError("Kunde inte hämta budskapsbiblioteket")
      })
    return () => {
      cancelled = true
    }
  }, [libraryType])

  const filteredLibrary = useMemo(() => {
    const q = libQuery.trim().toLowerCase()
    if (!q) return library
    return library.filter(
      (m) =>
        m.title.toLowerCase().includes(q) || m.body.toLowerCase().includes(q),
    )
  }, [library, libQuery])

  function selectLibraryMessage(messageId: string) {
    if (!messageId) {
      onChange({ ...inj, message_id: null })
      return
    }
    const msg = library.find((m) => m.id === messageId)
    if (!msg) return
    onChange({
      ...inj,
      message_id: msg.id,
      text: msg.body,
      url: msg.source_url ?? "",
      mode: "text",
      sourceDomain: "",
      isVideo: false,
      fetching: false,
    })
    setScratchOpen(false)
  }

  function enableScratch() {
    setScratchOpen(true)
    onChange({ ...inj, message_id: null })
  }

  return (
    <div className="inj-event">
      <div className="inj-top">
        <div className="inj-field">
          <label htmlFor={typeId}>Typ</label>
          <select
            id={typeId}
            value={inj.type}
            onChange={(e) =>
              onChange({
                ...inj,
                type: e.target.value as Injection["type"],
                message_id: null,
              })
            }
          >
            <option value="party_post">Partipost</option>
            <option value="news_post">Nyhetspost</option>
            <option value="ad_post">Reklampost</option>
          </select>
        </div>
        <div className="inj-field">
          <label htmlFor={senderId}>Avsändare</label>
          <input
            id={senderId}
            placeholder="t.ex. @partihandle eller Lokalnyheterna"
            value={inj.sender}
            onChange={(e) => onChange({ ...inj, sender: e.target.value })}
          />
        </div>
        <button type="button" className="inj-remove" onClick={onRemove} title="Ta bort event">
          ✕
        </button>
      </div>

      <div className="inj-field">
        <label htmlFor={searchId}>Sök i biblioteket</label>
        <input
          id={searchId}
          placeholder="Sök titel…"
          value={libQuery}
          onChange={(e) => setLibQuery(e.target.value)}
        />
      </div>

      <div className="inj-field">
        <label htmlFor={libraryId}>Budskap från biblioteket</label>
        <select
          id={libraryId}
          value={inj.message_id ?? ""}
          onChange={(e) => selectLibraryMessage(e.target.value)}
        >
          <option value="">— Välj sparat budskap —</option>
          {filteredLibrary.map((m) => (
            <option key={m.id} value={m.id}>
              {m.title}
            </option>
          ))}
        </select>
        {libError && <p className="inj-source">{libError}</p>}
        {!libError && library.length === 0 && (
          <p className="inj-source">
            Inga {libraryType === "news" ? "nyheter" : "poster"} i biblioteket.{" "}
            <Link to="/messages/new">Öppna verkstaden</Link>
          </p>
        )}
      </div>

      {inj.message_id && (
        <div className="inj-field">
          <label>Förhandsvisning (snapshottas vid start)</label>
          <textarea id={textId} value={inj.text} readOnly rows={4} />
        </div>
      )}

      <div className="inj-mode-switch">
        <button
          type="button"
          className={scratchOpen && !inj.message_id ? "on" : ""}
          onClick={enableScratch}
        >
          Scratch / tillfällig text
        </button>
      </div>

      {scratchOpen && !inj.message_id && (
        <div className="inj-field">
          <label htmlFor={textId}>
            Tillfällig text (sparas inte i biblioteket — bara denna körning)
          </label>
          <textarea
            id={textId}
            placeholder="Engångstext för snabb test…"
            value={inj.text}
            onChange={(e) =>
              onChange({ ...inj, message_id: null, text: e.target.value, mode: "text" })
            }
          />
        </div>
      )}
    </div>
  )
}

type TickCardProps = {
  tick: Tick
  open: boolean
  onToggle: () => void
  onUpdate: (next: Tick) => void
  onRemove: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  onBranch: () => void
  canBranch: boolean
  isBranchNode?: boolean
}

export function TickCard({
  tick,
  open,
  onToggle,
  onUpdate,
  onRemove,
  onMoveUp,
  onMoveDown,
  onBranch,
  canBranch,
  isBranchNode = false,
}: TickCardProps) {
  const summary = tick.silent
    ? "Tyst tick — endast mätning"
    : tick.injections.length
      ? tick.injections.length + " event · " + tick.rounds + " ronder"
      : "Ingen injektion ännu"

  function updateInj(i: number, next: Injection) {
    const arr = [...tick.injections]
    arr[i] = next
    onUpdate({ ...tick, injections: arr })
  }
  function removeInj(i: number) {
    onUpdate({
      ...tick,
      injections: tick.injections.filter((_, idx) => idx !== i),
    })
  }
  function addInj() {
    onUpdate({ ...tick, injections: [...tick.injections, makeInjection()] })
  }
  function toggleMeas(id: string) {
    const has = tick.measurements.includes(id)
    onUpdate({
      ...tick,
      measurements: has
        ? tick.measurements.filter((m) => m !== id)
        : [...tick.measurements, id],
    })
  }

  return (
    <div className="tl-tick">
      <button
        type="button"
        className={
          "tl-node" +
          (tick.silent ? " silent" : "") +
          (isBranchNode ? " branchnode" : "")
        }
        onClick={onToggle}
        aria-expanded={open}
        aria-label={"Dag " + tick.day}
      >
        {tick.day}
      </button>
      <div className={"tl-card" + (open ? " open" : "")}>
        <div className="tl-head">
          <button type="button" className="tl-head-main" onClick={onToggle}>
            <div className="day">Dag {tick.day}</div>
            <div className="sum">
              {tick.silent ? <em>{summary}</em> : summary}
            </div>
            {!tick.silent && (
              <div className="rounds-mini">
                {[1, 2, 3, 4, 5].map((n) => (
                  <div key={n} className={"d" + (n <= tick.rounds ? " on" : "")} />
                ))}
              </div>
            )}
            <div className="caret">{open ? "▲" : "▼"}</div>
          </button>
          <div className="tl-head-actions">
            <button type="button" className="tl-icon-btn" onClick={onMoveUp} title="Flytta upp">
              ↑
            </button>
            <button type="button" className="tl-icon-btn" onClick={onMoveDown} title="Flytta ner">
              ↓
            </button>
            <button
              type="button"
              className="tl-icon-btn danger"
              onClick={onRemove}
              title="Ta bort tick"
            >
              ✕
            </button>
          </div>
        </div>
        {open && (
          <div className="tl-body">
            <div className="silent-toggle-row">
              <div>
                <div className="t">Tyst tick</div>
                <div className="s">
                  Ingen injektion — bara mätning av läget den här dagen.
                </div>
              </div>
              <button
                type="button"
                className={"toggle" + (tick.silent ? " on" : "")}
                onClick={() => onUpdate({ ...tick, silent: !tick.silent })}
                aria-pressed={tick.silent}
                aria-label="Tyst tick"
              />
            </div>

            {!tick.silent && (
              <>
                <div>
                  <span className="tl-row-lbl">Injektionsfas</span>
                  {tick.injections.map((inj, i) => (
                    <InjectionEditor
                      key={inj.key}
                      inj={inj}
                      onChange={(n) => updateInj(i, n)}
                      onRemove={() => removeInj(i)}
                    />
                  ))}
                  <button type="button" className="add-inj-btn" onClick={addInj}>
                    + Lägg till event
                  </button>
                </div>
                <div>
                  <span className="tl-row-lbl">
                    Ronder efter injektion
                    <span className="tl-row-desc">
                      Antal simulerade svarsronder som körs efter injektionen, innan
                      nästa mätning tas.
                    </span>
                  </span>
                  <RoundsDots
                    value={tick.rounds}
                    onChange={(n) => onUpdate({ ...tick, rounds: n })}
                  />
                </div>
              </>
            )}

            <div>
              <span className="tl-row-lbl">Mätpunkter</span>
              <div className="meas-chips">
                {MEASUREMENTS.map((m) => (
                  <button
                    type="button"
                    key={m.id}
                    className={
                      "meas-chip" +
                      (tick.measurements.includes(m.id) ? " on" : "")
                    }
                    onClick={() => toggleMeas(m.id)}
                    aria-pressed={tick.measurements.includes(m.id)}
                  >
                    {m.label}
                    <span className="mid">{m.id}</span>
                  </button>
                ))}
              </div>
            </div>

            {canBranch && (
              <div className="branch-cta">
                <button type="button" className="branch-link" onClick={onBranch}>
                  Förgrena till A/B från denna tick →
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

type TickColumnProps = {
  ticks: Tick[]
  openKey: string | null
  setOpenKey: (key: string | null) => void
  updateTick: (i: number, next: Tick) => void
  removeTick: (i: number) => void
  moveTick: (i: number, dir: number) => void
  addTick: () => void
  onBranch: (i: number) => void
  branchable: boolean
  showAdd?: boolean
}

export function TickColumn({
  ticks,
  openKey,
  setOpenKey,
  updateTick,
  removeTick,
  moveTick,
  addTick,
  onBranch,
  branchable,
  showAdd = true,
}: TickColumnProps) {
  return (
    <div className="tl-col">
      {ticks.map((t, i) => (
        <TickCard
          key={t.key}
          tick={t}
          open={openKey === t.key}
          onToggle={() => setOpenKey(openKey === t.key ? null : t.key)}
          onUpdate={(n) => updateTick(i, n)}
          onRemove={() => removeTick(i)}
          onMoveUp={() => moveTick(i, -1)}
          onMoveDown={() => moveTick(i, 1)}
          onBranch={() => onBranch(i)}
          canBranch={branchable}
        />
      ))}
      {showAdd && (
        <button type="button" className="add-tick-btn" onClick={addTick}>
          + Lägg till tick
        </button>
      )}
    </div>
  )
}
