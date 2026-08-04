import { useState } from "react"
import { Link } from "react-router-dom"
import { RunActionCard } from "@/components/runs/RunActionCard"
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

const STEP_TITLES = ["Grund", "Tidslinje", "Granska & spara"] as const

export type RunCreateWizardProps = {
  name: string
  onNameChange: (value: string) => void
  startDate: string
  onStartDateChange: (value: string) => void
  seed: string
  onSeedChange: (value: string) => void
  onSeedRefresh: () => void
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
  onSave: () => void
  onStart: () => void
  onValidationError: (message: string) => void
}

export function RunCreateWizard(props: RunCreateWizardProps) {
  const [cur, setCur] = useState(1)
  const [maxReached, setMaxReached] = useState(1)

  function goTo(step: number) {
    setCur(step)
    setMaxReached((m) => Math.max(m, step))
  }

  function next() {
    const check = validateRunWizardStep(cur as 1 | 2 | 3, {
      name: props.name,
      populationId: props.popId,
      populationSize: props.population.size,
      seed: props.seed,
      startDate: props.startDate,
      mainTicks: props.mainTicks,
      branch: props.branch,
    })
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
          <h1>Ny körning</h1>
          <p>Steg-för-steg — spara när du är klar för att redigera fritt.</p>
        </div>
        <div className="head-row-aside">
          {cur === 3 && (
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
              onSave={props.onSave}
              onStart={props.onStart}
            />
          )}
          <Link
            to="/runs/new?mode=quick"
            className="head-row-link text-sm text-db-gold-700 underline-offset-2 hover:underline"
          >
            Snabbskapande →
          </Link>
        </div>
      </div>

      <div className="stepper stepper-3">
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

      {cur === 1 && (
        <section>
          <div className="section-head">
            <span className="kicker">Steg 1 · Grund</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              Namn, population och seed
            </h1>
            <p>
              Välj vilken population som ska reagera och ett seed för
              reproducerbara resultat.
            </p>
          </div>
          <Card className="id-card mb-9 gap-0 overflow-visible py-0 ring-1 ring-border">
            <CardContent className="px-0">
              <div className="id-grid">
                <RunIdentityFields
                  name={props.name}
                  onNameChange={props.onNameChange}
                  startDate={props.startDate}
                  onStartDateChange={props.onStartDateChange}
                  seed={props.seed}
                  onSeedChange={props.onSeedChange}
                  onSeedRefresh={props.onSeedRefresh}
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
            <span className="kicker">Steg 2 · Tidslinje</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              Bygg scenario och budskap
            </h1>
            <p>
              Klicka på en dag för att konfigurera budskap i en dialog. Valfritt:
              dela tidslinjen i version A och B för A/B-test.
            </p>
          </div>
          <RunTimelineSection
            mainTicks={props.mainTicks}
            branch={props.branch}
            activeMain={props.activeMain}
            seed={props.seed}
            population={props.population}
            openKey={props.openKey}
            onOpenKeyChange={props.onOpenKeyChange}
            onUpdateMain={props.onUpdateMain}
            onRemoveMain={props.onRemoveMain}
            onMoveMain={props.onMoveMain}
            onAddMain={props.onAddMain}
            onStartBranch={props.onStartBranch}
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
            <span className="kicker">Steg 3 · Granska & spara</span>
            <h1
              style={{
                font: "var(--text-h1)",
                fontFamily: "'Bai Jamjuree', sans-serif",
                fontWeight: 400,
              }}
            >
              Granska och spara
            </h1>
            <p>
              Spara körningen som utkast eller starta simuleringen. Plattform
              väljs i verktygsraden ovanför.
            </p>
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
    </>
  )
}
