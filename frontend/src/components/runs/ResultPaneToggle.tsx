import { useLocale, type MessageKey } from "@/i18n"

export type ResultPaneMode = "feed" | "activity" | "both"

const MODES: ResultPaneMode[] = ["feed", "activity", "both"]

const MODE_LABEL: Record<ResultPaneMode, MessageKey> = {
  feed: "runs.results.paneFeed",
  activity: "runs.results.paneActivity",
  both: "runs.results.paneBoth",
}

export function ResultPaneToggle({
  value,
  onChange,
}: {
  value: ResultPaneMode
  onChange: (value: ResultPaneMode) => void
}) {
  const { t } = useLocale()
  return (
    <div
      className="view-toggle"
      role="group"
      aria-label={t("runs.results.paneToggleAria")}
    >
      {MODES.map((mode) => (
        <button
          key={mode}
          type="button"
          className={value === mode ? "on" : undefined}
          aria-pressed={value === mode}
          onClick={() => onChange(mode)}
        >
          {t(MODE_LABEL[mode])}
        </button>
      ))}
    </div>
  )
}

export function paneShowsFeed(mode: ResultPaneMode): boolean {
  return mode !== "activity"
}

export function paneShowsActivity(mode: ResultPaneMode): boolean {
  return mode !== "feed"
}
