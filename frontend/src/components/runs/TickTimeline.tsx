import type { Tick } from "@/data/runs-types"
import { TickDayModal } from "@/components/runs/TickDayModal"

function tickSummary(tick: Tick): string {
  const ivCount = (tick.interviews ?? []).length
  const ivSuffix =
    ivCount > 0 ? ` · ${ivCount} intervju${ivCount === 1 ? "" : "er"}` : ""
  if (tick.silent) {
    return (
      "Tyst dag — ingen injektion · " + tick.rounds + " reaktionsronder" + ivSuffix
    )
  }
  if (tick.injections.length) {
    return tick.injections.length + " event · " + tick.rounds + " ronder" + ivSuffix
  }
  if (ivCount > 0) {
    return tick.rounds + " ronder" + ivSuffix
  }
  return "Ingen injektion ännu — klicka för att konfigurera"
}

type TickCardProps = {
  tick: Tick
  onEdit: () => void
  onRemove: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  canBranch?: boolean
  onBranch?: () => void
  onStimulusControl?: () => void
  isBranchNode?: boolean
}

function TickCard({
  tick,
  onEdit,
  onRemove,
  onMoveUp,
  onMoveDown,
  canBranch = false,
  onBranch,
  onStimulusControl,
  isBranchNode = false,
}: TickCardProps) {
  const summary = tickSummary(tick)

  return (
    <div className="tl-tick">
      <button
        type="button"
        className={
          "tl-node" +
          (tick.silent ? " silent" : "") +
          (isBranchNode ? " branchnode" : "")
        }
        onClick={onEdit}
        aria-label={"Redigera dag " + tick.day}
      >
        {tick.day}
      </button>
      <div className="tl-card">
        <div className="tl-head">
          <button type="button" className="tl-head-main" onClick={onEdit}>
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
            <span className="tl-edit-hint">Redigera</span>
          </button>
          <div className="tl-head-actions">
            {canBranch && onBranch && (
              <button
                type="button"
                className="tl-branch-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  onBranch()
                }}
                title="Förgrena till A/B från denna dag"
              >
                A/B
              </button>
            )}
            {canBranch && onStimulusControl && (
              <button
                type="button"
                className="tl-branch-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  onStimulusControl()
                }}
                title="Stimulus vs kontroll från denna dag (A med injektion, B tyst)"
              >
                S/K
              </button>
            )}
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
              title="Ta bort dag"
            >
              ✕
            </button>
          </div>
        </div>
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
  onStimulusControl?: (i: number) => void
  branchable: boolean
  showAdd?: boolean
  populationId?: number | null
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
  onStimulusControl,
  branchable,
  showAdd = true,
  populationId = null,
}: TickColumnProps) {
  const editingIndex = ticks.findIndex((t) => t.key === openKey)
  const editingTick = editingIndex >= 0 ? ticks[editingIndex] : null

  function closeModal() {
    setOpenKey(null)
  }

  function handleRemove(index: number) {
    if (openKey === ticks[index]?.key) setOpenKey(null)
    removeTick(index)
  }

  return (
    <div className="tl-col">
      {ticks.map((t, i) => (
        <TickCard
          key={t.key}
          tick={t}
          onEdit={() => setOpenKey(t.key)}
          onRemove={() => handleRemove(i)}
          onMoveUp={() => moveTick(i, -1)}
          onMoveDown={() => moveTick(i, 1)}
          canBranch={branchable}
          onBranch={() => onBranch(i)}
          onStimulusControl={
            onStimulusControl ? () => onStimulusControl(i) : undefined
          }
        />
      ))}
      {showAdd && (
        <button type="button" className="add-tick-btn" onClick={addTick}>
          + Lägg till dag
        </button>
      )}

      <TickDayModal
        open={editingTick != null}
        tick={editingTick}
        populationId={populationId}
        onUpdate={(next) => {
          if (editingIndex >= 0) updateTick(editingIndex, next)
        }}
        onClose={closeModal}
      />
    </div>
  )
}
