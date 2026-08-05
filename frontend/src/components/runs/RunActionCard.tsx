import { Card, CardContent } from "@/components/ui/card"
import type { OasisPlatform, RunStatus } from "@/data/runs-types"
import { useLocale } from "@/i18n"

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
  const { t } = useLocale()
  const isRunning = runStatus === "running"
  const startLabel = isRunning
    ? t("runs.actions.running")
    : runStatus === "done" || runStatus === "failed"
      ? t("runs.actions.rerun")
      : t("runs.actions.start")
  const saveBusy = pendingAction === "save"
  const startBusy = pendingAction === "start"
  const barStartLabel = isRunning
    ? t("runs.actions.running")
    : runStatus === "done" || runStatus === "failed"
      ? t("runs.actions.rerun")
      : startBusy
        ? t("runs.actions.starting")
        : t("runs.actions.startShort")
  const barSaveLabel = saveBusy ? t("common.saving") : t("common.save")
  const cardSaveLabel = saveBusy ? t("common.saving") : t("runs.actions.saveRun")
  const cardStartLabel = isRunning
    ? t("runs.actions.running")
    : startBusy
      ? t("runs.actions.starting")
      : startLabel
  const controlsLocked = saving || disabled || isRunning
  const content = (
    <>
      <div className="start-summary">
        <div className="start-stat start-stat-platform">
          <select
            id="run-platform"
            className="run-platform-select"
            value={platform}
            disabled={controlsLocked}
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
          <div className="l">{t("runs.actions.ticks")}</div>
        </div>
        <div className="start-stat">
          <div className="n">{populationSize}</div>
          <div className="l">{t("runs.actions.personas")}</div>
        </div>
        <div className="start-stat">
          <div className="n">{variantCount}</div>
          <div className="l">{t("runs.actions.variants")}</div>
        </div>
      </div>
      <div className="start-actions">
        <div className="start-buttons">
          <button
            type="button"
            className="btn-save"
            disabled={controlsLocked}
            onClick={onSave}
          >
            {layout === "bar" ? barSaveLabel : cardSaveLabel}
          </button>
          <button
            type="button"
            className="btn-run"
            disabled={controlsLocked}
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
