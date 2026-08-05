import { TickColumn } from "@/components/runs/TickTimeline"
import type { BranchState, RunPopulationOption, Tick } from "@/data/runs-types"
import { useLocale } from "@/i18n"

export type RunTimelineSectionProps = {
  mainTicks: Tick[]
  branch: BranchState | null
  activeMain: Tick[]
  population: RunPopulationOption
  openKey: string | null
  onOpenKeyChange: (key: string | null) => void
  onUpdateMain: (index: number, tick: Tick) => void
  onRemoveMain: (index: number) => void
  onMoveMain: (index: number, direction: number) => void
  onAddMain: () => void
  onStartBranch: (index: number) => void
  onStartStimulusControlBranch?: (index: number) => void
  onClearBranch: () => void
  onUpdateBranchTick: (side: "a" | "b", index: number, tick: Tick) => void
  onRemoveBranchTick: (side: "a" | "b", index: number) => void
  onMoveBranchTick: (side: "a" | "b", index: number, direction: number) => void
  onAddBranchTick: (side: "a" | "b") => void
  disabled?: boolean
  hideKicker?: boolean
}

export function RunTimelineSection({
  mainTicks,
  branch,
  activeMain,
  population,
  openKey,
  onOpenKeyChange,
  onUpdateMain,
  onRemoveMain,
  onMoveMain,
  onAddMain,
  onStartBranch,
  onStartStimulusControlBranch,
  onClearBranch,
  onUpdateBranchTick,
  onRemoveBranchTick,
  onMoveBranchTick,
  onAddBranchTick,
  disabled = false,
  hideKicker = false,
}: RunTimelineSectionProps) {
  const { t } = useLocale()

  return (
    <div className="tl-section">
      {!hideKicker ? <span className="tl-kicker">{t("runs.timeline.kicker")}</span> : null}
      <TickColumn
        ticks={activeMain}
        openKey={openKey}
        setOpenKey={onOpenKeyChange}
        updateTick={onUpdateMain}
        removeTick={onRemoveMain}
        moveTick={onMoveMain}
        addTick={branch || disabled ? () => undefined : onAddMain}
        onBranch={onStartBranch}
        onStimulusControl={onStartStimulusControlBranch}
        branchable={!branch && !disabled}
        showAdd={!branch && !disabled}
        populationId={population.id}
      />

      {branch && (
        <>
          <div className="fork-wrap">
            <div className="fork-line" />
            <div className="fork-bar">
              <span className="t">
                {t("runs.timeline.splitAt", {
                  day: mainTicks[branch.afterIndex].day,
                })}
              </span>
              <span className="s">
                {branch.mode === "stimulus_control"
                  ? t("runs.timeline.splitStimulus", { name: population.name })
                  : t("runs.timeline.splitAb", { name: population.name })}
              </span>
              {!disabled ? (
                <button type="button" onClick={onClearBranch}>
                  {t("runs.timeline.removeBranch")}
                </button>
              ) : null}
            </div>
          </div>
          <div className="branches-grid">
            <div>
              <div className="branch-head">
                <span className="branch-badge a">A</span>
                <span className="lbl">
                  {branch.mode === "stimulus_control"
                    ? t("runs.timeline.stimulusA")
                    : t("runs.timeline.versionA")}
                </span>
              </div>
              <TickColumn
                ticks={branch.a}
                openKey={openKey}
                setOpenKey={onOpenKeyChange}
                updateTick={(i, n) => onUpdateBranchTick("a", i, n)}
                removeTick={(i) => onRemoveBranchTick("a", i)}
                moveTick={(i, d) => onMoveBranchTick("a", i, d)}
                addTick={() => onAddBranchTick("a")}
                onBranch={() => undefined}
                branchable={false}
                populationId={population.id}
              />
            </div>
            <div>
              <div className="branch-head">
                <span className="branch-badge b">B</span>
                <span className="lbl">
                  {branch.mode === "stimulus_control"
                    ? t("runs.timeline.controlB")
                    : t("runs.timeline.versionB")}
                </span>
              </div>
              <TickColumn
                ticks={branch.b}
                openKey={openKey}
                setOpenKey={onOpenKeyChange}
                updateTick={(i, n) => onUpdateBranchTick("b", i, n)}
                removeTick={(i) => onRemoveBranchTick("b", i)}
                moveTick={(i, d) => onMoveBranchTick("b", i, d)}
                addTick={() => onAddBranchTick("b")}
                onBranch={() => undefined}
                branchable={false}
                populationId={population.id}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
