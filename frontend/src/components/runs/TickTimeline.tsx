import { TickDayModal } from "@/components/runs/TickDayModal"
import type { Tick } from "@/data/runs-types"
import { useLocale, type MessageKey, type TranslateParams } from "@/i18n"

type Translate = (key: MessageKey, params?: TranslateParams) => string

function tickSummary(tick: Tick, t: Translate): string {
  const ivCount = (tick.interviews ?? []).length
  const ivSuffix =
    ivCount > 0
      ? t(ivCount === 1 ? "runs.timeline.interviewOne" : "runs.timeline.interviewMany", {
          count: ivCount,
        })
      : ""
  if (tick.silent) {
    return t("runs.timeline.silentSummary", {
      rounds: tick.rounds,
      interviews: ivSuffix,
    })
  }
  if (tick.injections.length) {
    return t("runs.timeline.eventsSummary", {
      events: tick.injections.length,
      rounds: tick.rounds,
      interviews: ivSuffix,
    })
  }
  if (ivCount > 0) {
    return t("runs.timeline.roundsOnly", {
      rounds: tick.rounds,
      interviews: ivSuffix,
    })
  }
  return t("runs.timeline.emptySummary")
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
  const { t } = useLocale()
  const summary = tickSummary(tick, t)

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
        aria-label={t("runs.timeline.editDayAria", { day: tick.day })}
      >
        {tick.day}
      </button>
      <div className="tl-card">
        <div className="tl-head">
          <button type="button" className="tl-head-main" onClick={onEdit}>
            <div className="day">{t("runs.timeline.dayLabel", { day: tick.day })}</div>
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
            <span className="tl-edit-hint">{t("runs.timeline.edit")}</span>
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
                title={t("runs.timeline.branchAbTitle")}
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
                title={t("runs.timeline.branchSkTitle")}
              >
                S/K
              </button>
            )}
            <button type="button" className="tl-icon-btn" onClick={onMoveUp} title={t("runs.timeline.moveUp")}>
              ↑
            </button>
            <button type="button" className="tl-icon-btn" onClick={onMoveDown} title={t("runs.timeline.moveDown")}>
              ↓
            </button>
            <button
              type="button"
              className="tl-icon-btn danger"
              onClick={onRemove}
              title={t("runs.timeline.removeDay")}
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
  const { t } = useLocale()
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
          {t("runs.timeline.addDay")}
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
