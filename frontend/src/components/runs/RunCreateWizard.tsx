import { useState } from "react"
import { Link } from "react-router-dom"
import { RunActionCard } from "@/components/runs/RunActionCard"
import { RunAgentToolsFields } from "@/components/runs/RunAgentToolsFields"
import { RunIdentityFields } from "@/components/runs/RunIdentityFields"
import { RunTimelineSection } from "@/components/runs/RunTimelineSection"
import { AdminButton } from "@/components/ui/admin-button"
import { Card, CardContent } from "@/components/ui/card"
import { validateRunWizardStep } from "@/data/runValidation"
import type {
  BranchState,
  OasisRunOptions,
  RunPopulationOption,
  RunStatus,
  Tick,
} from "@/data/runs-types"
import { useLocale } from "@/i18n"

export type RunCreateWizardProps = {
  name: string
  onNameChange: (value: string) => void
  startDate: string
  onStartDateChange: (value: string) => void
  populations: RunPopulationOption[]
  popId: number | null
  onPopIdChange: (id: number) => void
  population: RunPopulationOption
  popOpen: boolean
  onPopOpenChange: (open: boolean) => void
  mainTicks: Tick[]
  branch: BranchState | null
  activeMain: Tick[]
  openKey: string | null
  onOpenKeyChange: (key: string | null) => void
  onUpdateMain: (index: number, tick: Tick) => void
  onRemoveMain: (index: number) => void
  onMoveMain: (index: number, direction: number) => void
  onAddMain: () => void
  onStartBranch: (index: number) => void
  onStartAbFromBeginning?: () => void
  onStartStimulusControlBranch?: (index: number) => void
  onClearBranch: () => void
  onUpdateBranchTick: (side: "a" | "b", index: number, tick: Tick) => void
  onRemoveBranchTick: (side: "a" | "b", index: number) => void
  onMoveBranchTick: (side: "a" | "b", index: number, direction: number) => void
  onAddBranchTick: (side: "a" | "b") => void
  oasisOptions: OasisRunOptions
  onOasisOptionsChange: (options: OasisRunOptions) => void
  tickCount: number
  variantCount: number
  runStatus: RunStatus
  saving: boolean
  pendingAction?: "save" | "start" | null
  disabled?: boolean
  onSave: () => void
  onStart: () => void
  onValidationError: (message: string) => void
}

export function RunCreateWizard(props: RunCreateWizardProps) {
  const { t } = useLocale()
  const [cur, setCur] = useState(1)
  const [maxReached, setMaxReached] = useState(1)
  const stepTitles = [
    t("runs.wizard.stepGrund"),
    t("runs.wizard.stepTimeline"),
    t("runs.wizard.stepTools"),
    t("runs.wizard.stepReview"),
  ] as const

  function goTo(step: number) {
    setCur(step)
    setMaxReached((m) => Math.max(m, step))
  }

  function next() {
    const check = validateRunWizardStep(cur as 1 | 2 | 3 | 4, {
      name: props.name,
      populationId: props.popId,
      populationSize: props.population.size,
      startDate: props.startDate,
      mainTicks: props.mainTicks,
      branch: props.branch,
    }, t)
    if (!check.ok) {
      props.onValidationError(check.errors.slice(0, 2).join(" · "))
      return
    }
    goTo(cur + 1)
  }

  function back() {
    if (cur > 1) setCur(cur - 1)
  }

  return (
    <>
      <div className="head-row" style={{ marginBottom: 24 }}>
        <div className="head-row-main">
          <h1>{t("runs.wizard.title")}</h1>
          <p>{t("runs.wizard.intro")}</p>
        </div>
        <div className="head-row-aside">
          {cur === 4 && (
            <RunActionCard
              layout="bar"
              platform={props.oasisOptions.platform}
              onPlatformChange={(platform) =>
                props.onOasisOptionsChange({
                  ...props.oasisOptions,
                  platform,
                })
              }
              tickCount={props.tickCount}
              populationSize={props.population.size}
              variantCount={props.variantCount}
              runStatus={props.runStatus}
              saving={props.saving}
              pendingAction={props.pendingAction}
              disabled={props.disabled}
              onSave={props.onSave}
              onStart={props.onStart}
            />
          )}
          <Link
            to="/runs/new?mode=quick"
            className="head-row-link text-sm text-db-gold-700 underline-offset-2 hover:underline"
          >
            {t("runs.wizard.quickLink")}
          </Link>
        </div>
      </div>

      <div className="stepper stepper-4">
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
            <span className="kicker">{t("runs.wizard.kicker1")}</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              {t("runs.wizard.heading1")}
            </h1>
            <p>{t("runs.wizard.body1")}</p>
          </div>
          <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
            <CardContent className="px-0">
              <div className="id-grid">
                <RunIdentityFields
                  name={props.name}
                  onNameChange={props.onNameChange}
                  startDate={props.startDate}
                  onStartDateChange={props.onStartDateChange}
                  populations={props.populations}
                  popId={props.popId}
                  onPopIdChange={props.onPopIdChange}
                  population={props.population}
                  popOpen={props.popOpen}
                  onPopOpenChange={props.onPopOpenChange}
                  allowPopulationCreatePost={
                    props.oasisOptions.allow_population_create_post
                  }
                  onAllowPopulationCreatePostChange={(checked) =>
                    props.onOasisOptionsChange({
                      ...props.oasisOptions,
                      allow_population_create_post: checked,
                    })
                  }
                />
              </div>
            </CardContent>
          </Card>
        </section>
      )}

      {cur === 2 && (
        <section>
          <div className="section-head">
            <span className="kicker">{t("runs.wizard.kicker2")}</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              {t("runs.wizard.heading2")}
            </h1>
            <p>{t("runs.wizard.body2")}</p>
          </div>
          <RunTimelineSection
            mainTicks={props.mainTicks}
            branch={props.branch}
            activeMain={props.activeMain}
            population={props.population}
            openKey={props.openKey}
            onOpenKeyChange={props.onOpenKeyChange}
            onUpdateMain={props.onUpdateMain}
            onRemoveMain={props.onRemoveMain}
            onMoveMain={props.onMoveMain}
            onAddMain={props.onAddMain}
            onStartBranch={props.onStartBranch}
            onStartAbFromBeginning={props.onStartAbFromBeginning}
            onStartStimulusControlBranch={props.onStartStimulusControlBranch}
            onClearBranch={() => props.onClearBranch()}
            onUpdateBranchTick={props.onUpdateBranchTick}
            onRemoveBranchTick={props.onRemoveBranchTick}
            onMoveBranchTick={props.onMoveBranchTick}
            onAddBranchTick={props.onAddBranchTick}
          />
        </section>
      )}

      {cur === 3 && (
        <section>
          <div className="section-head">
            <span className="kicker">{t("runs.wizard.kicker3")}</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              {t("runs.wizard.heading3")}
            </h1>
            <p>{t("runs.wizard.body3")}</p>
          </div>
          <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
            <CardContent className="px-0">
              <div className="id-grid">
                <RunAgentToolsFields
                  options={props.oasisOptions}
                  onChange={props.onOasisOptionsChange}
                  disabled={props.disabled}
                />
              </div>
            </CardContent>
          </Card>
        </section>
      )}

      {cur === 4 && (
        <section>
          <div className="section-head">
            <span className="kicker">{t("runs.wizard.kicker4")}</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              {t("runs.wizard.heading4")}
            </h1>
            <p>{t("runs.wizard.body4")}</p>
          </div>
        </section>
      )}

      <div className="nav-bar">
        <AdminButton variant="secondary" disabled={cur === 1} onClick={back}>
          {t("common.back")}
        </AdminButton>
        {cur !== 4 && (
          <AdminButton variant="primary" onClick={next}>
            {t("common.next")}
          </AdminButton>
        )}
      </div>
    </>
  )
}
