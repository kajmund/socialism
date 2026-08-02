import {
  MEASUREMENTS,
  extractDomain,
  looksLikeVideo,
  makeInjection,
} from "@/data/runs"
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
  const urlId = `inj-url-${inj.key}`
  const textId = `inj-text-${inj.key}`

  function fetchLink() {
    if (!inj.url) return
    onChange({ ...inj, fetching: true })
    window.setTimeout(() => {
      onChange({
        ...inj,
        fetching: false,
        text: "Sammanfattning av innehållet på länken (redigera vid behov innan det sparas som injektionstext).",
        sourceDomain: extractDomain(inj.url),
        isVideo: looksLikeVideo(inj.url),
      })
    }, 1200)
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
              onChange({ ...inj, type: e.target.value as Injection["type"] })
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

      <div className="inj-mode-switch">
        <button
          type="button"
          className={inj.mode === "text" ? "on" : ""}
          onClick={() => onChange({ ...inj, mode: "text" })}
        >
          Skriv/klistra in text
        </button>
        <button
          type="button"
          className={inj.mode === "link" ? "on" : ""}
          onClick={() => onChange({ ...inj, mode: "link" })}
        >
          Klistra in en länk
        </button>
      </div>

      {inj.mode === "link" && (
        <div className="inj-field">
          <label htmlFor={urlId}>URL</label>
          <div className="inj-link-row">
            <input
              id={urlId}
              placeholder="Klistra in länk till artikel, klipp eller webbsida..."
              value={inj.url}
              onChange={(e) => onChange({ ...inj, url: e.target.value })}
            />
            <button
              type="button"
              className="inj-fetch-btn"
              onClick={fetchLink}
              disabled={!inj.url || inj.fetching}
            >
              Hämta
            </button>
          </div>
        </div>
      )}

      {inj.mode === "link" && inj.fetching && (
        <div className="inj-fetching">
          <span className="spin" />
          Hämtar & sammanfattar...
        </div>
      )}

      <div className="inj-field">
        <label htmlFor={textId}>Textinnehåll</label>
        <textarea
          id={textId}
          placeholder="Skriv eller klistra in budskapets text här..."
          value={inj.text}
          onChange={(e) => onChange({ ...inj, text: e.target.value })}
        />
      </div>

      {inj.mode === "link" && inj.sourceDomain && !inj.fetching && (
        <div className="inj-source">
          {inj.isVideo && (
            <span className="src-video" title="Videokälla">
              ▶
            </span>
          )}
          <span className="src-icon">🔗</span>
          {inj.sourceDomain}
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
