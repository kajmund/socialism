import { Card, CardContent } from "@/components/ui/card"
import type { OasisPlatform, RunStatus } from "@/data/runs-types"

const PLATFORMS: { value: OasisPlatform; label: string }[] = [
  { value: "twitter", label: "Twitter" },
  { value: "reddit", label: "Reddit" },
]

export type RunActionCardProps = {
  platform: OasisPlatform
  onPlatformChange: (platform: OasisPlatform) => void
  tickCount: number
  populationSize: number
  variantCount: number
  runStatus: RunStatus
  saving: boolean
  pendingAction?: "save" | "start" | null
  disabled?: boolean
  layout?: "card" | "bar"
  onSave: () => void
  onStart: () => void
}

export function RunActionCard({
  platform,
  onPlatformChange,
  tickCount,
  populationSize,
  variantCount,
  runStatus,
  saving,
  pendingAction = null,
  disabled = false,
  layout = "card",
  onSave,
  onStart,
}: RunActionCardProps) {
  const startLabel =
    runStatus === "done" || runStatus === "failed" ? "Kör igen" : "Starta körning"
  const saveBusy = pendingAction === "save"
  const startBusy = pendingAction === "start"
  const barStartLabel =
    startLabel === "Kör igen" ? "Kör igen" : startBusy ? "Startar…" : "Starta"
  const barSaveLabel = saveBusy ? "Sparar…" : "Spara"
  const cardSaveLabel = saveBusy ? "Sparar…" : "Spara körning"
  const cardStartLabel = startBusy
    ? "Startar…"
    : startLabel

  const content = (
    <>
      <div className="start-summary">
        <div className="start-stat start-stat-platform">
          <select
            id="run-platform"
            className="run-platform-select"
            value={platform}
            disabled={disabled}
            onChange={(e) => onPlatformChange(e.target.value as OasisPlatform)}
          >
            {PLATFORMS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="start-stat">
          <div className="n">{tickCount}</div>
          <div className="l">Tickar</div>
        </div>
        <div className="start-stat">
          <div className="n">{populationSize}</div>
          <div className="l">Personas</div>
        </div>
        <div className="start-stat">
          <div className="n">{variantCount}</div>
          <div className="l">Varianter</div>
        </div>
      </div>
      <div className="start-actions">
        <div className="start-buttons">
          <button
            type="button"
            className="btn-save"
            disabled={saving || disabled}
            onClick={onSave}
          >
            {layout === "bar" ? barSaveLabel : cardSaveLabel}
          </button>
          <button
            type="button"
            className="btn-run"
            disabled={saving || disabled}
            onClick={onStart}
          >
            {layout === "bar" ? barStartLabel : cardStartLabel}
          </button>
        </div>
      </div>
    </>
  )

  if (layout === "bar") {
    return <div className="run-action-bar">{content}</div>
  }

  return (
    <Card className="start-card gap-0 ring-1 ring-border">
      <CardContent className="flex flex-wrap items-center justify-between gap-6 px-8 py-7">
        {content}
      </CardContent>
    </Card>
  )
}
