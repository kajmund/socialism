import { useState } from "react"
import { DEFAULT_SSR_TEMPERATURE } from "@/api/configurations"
import {
  DEFAULT_REPORT_THRESHOLDS,
  cloneReportThresholds,
  type ReportThresholds,
  type ReportThresholdValidationKey,
} from "@/api/reportThresholds"
import { useLocale, type MessageKey } from "@/i18n"
import { cn } from "@/lib/utils"

type SensitivityGroupId =
  | "temperature"
  | "verdict"
  | "diff"
  | "action_bands"
  | "score_weights"
  | "score_caps"
  | "score_triggers"
  | "takeaway"
  | "narrative"

type ReportThresholdsEditorProps = {
  value: ReportThresholds
  onChange: (next: ReportThresholds) => void
  validationKey: ReportThresholdValidationKey | null
  ssrTemperature: number
  onSsrTemperatureChange: (value: number) => void
}

type RatioFieldProps = {
  label: string
  value: number
  onChange: (ratio: number) => void
  id: string
  suffix: "%" | "pp"
}

type NumberFieldProps = {
  label: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  step?: number
  id: string
}

const BASIC_GROUPS: { id: SensitivityGroupId; labelKey: MessageKey }[] = [
  { id: "temperature", labelKey: "configurations.editor.navTemperature" },
  { id: "verdict", labelKey: "configurations.editor.navVerdict" },
  { id: "diff", labelKey: "configurations.editor.navDiff" },
  { id: "action_bands", labelKey: "configurations.editor.navActionBands" },
]

const ADVANCED_GROUPS: { id: SensitivityGroupId; labelKey: MessageKey }[] = [
  { id: "score_weights", labelKey: "configurations.editor.navScoreWeights" },
  { id: "score_caps", labelKey: "configurations.editor.navScoreCaps" },
  { id: "score_triggers", labelKey: "configurations.editor.navScoreTriggers" },
  { id: "takeaway", labelKey: "configurations.editor.navTakeaway" },
  { id: "narrative", labelKey: "configurations.editor.navNarrative" },
]

function ratioToDisplay(ratio: number): number {
  return Math.round(ratio * 1000) / 10
}

function displayToRatio(display: number): number {
  return display / 100
}

function CompactRatioField({ label, value, onChange, id, suffix }: RatioFieldProps) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1.5 block text-[0.78rem] text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          id={id}
          type="number"
          min={0}
          max={100}
          step={0.1}
          className="w-16 rounded-[var(--radius-sm)] border-[1.5px] border-[color:var(--border-hairline)] px-2.5 py-2 font-mono text-[0.85rem]"
          value={ratioToDisplay(value)}
          onChange={(e) => onChange(displayToRatio(Number(e.target.value)))}
        />
        <span className="text-xs text-muted-foreground">{suffix}</span>
      </div>
    </label>
  )
}

function CompactNumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  id,
}: NumberFieldProps) {
  return (
    <label htmlFor={id} className="block">
      <span className="mb-1.5 block text-[0.78rem] text-muted-foreground">{label}</span>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        className="w-16 rounded-[var(--radius-sm)] border-[1.5px] border-[color:var(--border-hairline)] px-2.5 py-2 font-mono text-[0.85rem]"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function GroupNavButton({
  label,
  selected,
  onSelect,
}: {
  label: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={cn(
        "block w-full rounded-[var(--radius-sm)] px-2 py-2 text-left text-[0.8rem]",
        selected
          ? "bg-db-ink-950 font-semibold text-white"
          : "bg-transparent font-normal text-[color:var(--text-body)]",
      )}
      onClick={onSelect}
    >
      {label}
    </button>
  )
}

export function ReportThresholdsEditor({
  value,
  onChange,
  validationKey,
  ssrTemperature,
  onSsrTemperatureChange,
}: ReportThresholdsEditorProps) {
  const { t, intl } = useLocale()
  const [groupId, setGroupId] = useState<SensitivityGroupId>("temperature")
  const isAdvanced = ADVANCED_GROUPS.some((g) => g.id === groupId)
  const temperatureLabel = new Intl.NumberFormat(intl, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(ssrTemperature)

  function patchVerdict(patch: Partial<ReportThresholds["verdict"]>) {
    onChange({ ...value, verdict: { ...value.verdict, ...patch } })
  }

  function patchDiff(patch: Partial<ReportThresholds["diff"]>) {
    onChange({ ...value, diff: { ...value.diff, ...patch } })
  }

  function patchActionBands(patch: Partial<ReportThresholds["recommendation"]["action_bands"]>) {
    onChange({
      ...value,
      recommendation: {
        ...value.recommendation,
        action_bands: { ...value.recommendation.action_bands, ...patch },
      },
    })
  }

  function patchScoreWeights(patch: Partial<ReportThresholds["recommendation"]["score_weights"]>) {
    onChange({
      ...value,
      recommendation: {
        ...value.recommendation,
        score_weights: { ...value.recommendation.score_weights, ...patch },
      },
    })
  }

  function patchScoreCaps(patch: Partial<ReportThresholds["recommendation"]["score_caps"]>) {
    onChange({
      ...value,
      recommendation: {
        ...value.recommendation,
        score_caps: { ...value.recommendation.score_caps, ...patch },
      },
    })
  }

  function patchScoreTriggers(
    patch: Partial<ReportThresholds["recommendation"]["score_triggers"]>,
  ) {
    onChange({
      ...value,
      recommendation: {
        ...value.recommendation,
        score_triggers: { ...value.recommendation.score_triggers, ...patch },
      },
    })
  }

  function patchNarrative(patch: Partial<ReportThresholds["recommendation"]["narrative"]>) {
    onChange({
      ...value,
      recommendation: {
        ...value.recommendation,
        narrative: { ...value.recommendation.narrative, ...patch },
      },
    })
  }

  function patchTakeaway(patch: Partial<ReportThresholds["takeaway"]>) {
    onChange({ ...value, takeaway: { ...value.takeaway, ...patch } })
  }

  function resetDefaults() {
    onSsrTemperatureChange(DEFAULT_SSR_TEMPERATURE)
    onChange(cloneReportThresholds(DEFAULT_REPORT_THRESHOLDS))
  }

  function renderGroup(id: SensitivityGroupId) {
    switch (id) {
      case "temperature":
        return (
          <label className="block">
            <span className="block text-[0.9rem] font-semibold">
              {t("configurations.editor.ssrTemperatureLabel")}
            </span>
            <span className="mb-2.5 mt-[3px] block text-[12.5px] text-muted-foreground">
              {t("configurations.editor.ssrTemperatureHint")}
            </span>
            <div className="flex items-center gap-3.5">
              <input
                type="range"
                min={0.05}
                max={2}
                step={0.05}
                className="max-w-xs flex-1 accent-db-ink-950"
                value={ssrTemperature}
                onChange={(e) => onSsrTemperatureChange(Number(e.target.value))}
              />
              <span className="w-11 text-right font-mono text-[0.85rem]">{temperatureLabel}</span>
            </div>
          </label>
        )
      case "verdict":
        return (
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-1 p-0 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupVerdict")}
            </legend>
            <span className="mb-3 mt-0.5 block text-xs text-muted-foreground">
              {t("configurations.editor.reportThresholds.groupVerdictHint")}
            </span>
            <div className="flex flex-wrap gap-4">
              <CompactRatioField
                id="rt-pos-strong"
                suffix="%"
                label={t("configurations.editor.reportThresholds.posStrongLabel")}
                value={value.verdict.pos_strong}
                onChange={(v) => patchVerdict({ pos_strong: v })}
              />
              <CompactRatioField
                id="rt-pos-mixed"
                suffix="%"
                label={t("configurations.editor.reportThresholds.posMixedLabel")}
                value={value.verdict.pos_mixed}
                onChange={(v) => patchVerdict({ pos_mixed: v })}
              />
              <CompactRatioField
                id="rt-crit-weak"
                suffix="%"
                label={t("configurations.editor.reportThresholds.critWeakLabel")}
                value={value.verdict.crit_weak}
                onChange={(v) => patchVerdict({ crit_weak: v })}
              />
            </div>
          </fieldset>
        )
      case "diff":
        return (
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-1 p-0 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupDiff")}
            </legend>
            <span className="mb-3 mt-0.5 block text-xs text-muted-foreground">
              {t("configurations.editor.reportThresholds.groupDiffHint")}
            </span>
            <div className="flex flex-wrap gap-4">
              <CompactRatioField
                id="rt-diff-clear"
                suffix="pp"
                label={t("configurations.editor.reportThresholds.diffClearLabel")}
                value={value.diff.clear}
                onChange={(v) => patchDiff({ clear: v })}
              />
              <CompactRatioField
                id="rt-diff-weak"
                suffix="pp"
                label={t("configurations.editor.reportThresholds.diffWeakLabel")}
                value={value.diff.weak}
                onChange={(v) => patchDiff({ weak: v })}
              />
              <CompactRatioField
                id="rt-topic-drift"
                suffix="%"
                label={t("configurations.editor.reportThresholds.topicDriftLabel")}
                value={value.topic_drift}
                onChange={(v) => onChange({ ...value, topic_drift: v })}
              />
            </div>
          </fieldset>
        )
      case "action_bands":
        return (
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-1 p-0 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupActionBands")}
            </legend>
            <span className="mb-3 mt-0.5 block text-xs text-muted-foreground">
              {t("configurations.editor.reportThresholds.groupActionBandsHint")}
            </span>
            <div className="flex flex-wrap gap-4">
              <CompactNumberField
                id="rt-ready"
                label={t("configurations.editor.reportThresholds.actionReadyLabel")}
                min={0}
                max={100}
                value={value.recommendation.action_bands.ready}
                onChange={(v) => patchActionBands({ ready: v })}
              />
              <CompactNumberField
                id="rt-minor-adjust"
                label={t("configurations.editor.reportThresholds.actionMinorAdjustLabel")}
                min={0}
                max={100}
                value={value.recommendation.action_bands.minor_adjust}
                onChange={(v) => patchActionBands({ minor_adjust: v })}
              />
              <CompactNumberField
                id="rt-revise"
                label={t("configurations.editor.reportThresholds.actionReviseLabel")}
                min={0}
                max={100}
                value={value.recommendation.action_bands.revise}
                onChange={(v) => patchActionBands({ revise: v })}
              />
            </div>
          </fieldset>
        )
      case "score_weights":
        return (
          <div>
            <div className="mb-3 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupScoreWeights")}
            </div>
            <div className="flex flex-wrap gap-3.5">
              <CompactNumberField
                id="rt-weight-positive"
                label={t("configurations.editor.reportThresholds.weightPositiveLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_weights.positive}
                onChange={(v) => patchScoreWeights({ positive: v })}
              />
              <CompactNumberField
                id="rt-weight-critical"
                label={t("configurations.editor.reportThresholds.weightCriticalLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_weights.critical_headroom}
                onChange={(v) => patchScoreWeights({ critical_headroom: v })}
              />
              <CompactNumberField
                id="rt-weight-likes"
                label={t("configurations.editor.reportThresholds.weightLikesLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_weights.injection_likes}
                onChange={(v) => patchScoreWeights({ injection_likes: v })}
              />
              <CompactNumberField
                id="rt-weight-engagement"
                label={t("configurations.editor.reportThresholds.weightEngagementLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_weights.engagement}
                onChange={(v) => patchScoreWeights({ engagement: v })}
              />
            </div>
          </div>
        )
      case "score_caps":
        return (
          <div>
            <div className="mb-3 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupScoreCaps")}
            </div>
            <div className="flex flex-wrap gap-3.5">
              <CompactNumberField
                id="rt-cap-zero-likes"
                label={t("configurations.editor.reportThresholds.capZeroLikesLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_caps.zero_likes_max}
                onChange={(v) => patchScoreCaps({ zero_likes_max: v })}
              />
              <CompactNumberField
                id="rt-cap-strong-floor"
                label={t("configurations.editor.reportThresholds.capStrongFloorLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_caps.strong_floor}
                onChange={(v) => patchScoreCaps({ strong_floor: v })}
              />
              <CompactNumberField
                id="rt-cap-weak-ceiling"
                label={t("configurations.editor.reportThresholds.capWeakCeilingLabel")}
                min={0}
                max={100}
                value={value.recommendation.score_caps.weak_ceiling}
                onChange={(v) => patchScoreCaps({ weak_ceiling: v })}
              />
              <CompactNumberField
                id="rt-cap-likes"
                label={t("configurations.editor.reportThresholds.capLikesLabel")}
                min={1}
                max={999}
                value={value.recommendation.score_caps.injection_likes_cap}
                onChange={(v) => patchScoreCaps({ injection_likes_cap: v })}
              />
              <CompactNumberField
                id="rt-cap-engagement"
                label={t("configurations.editor.reportThresholds.capEngagementLabel")}
                min={1}
                max={999}
                value={value.recommendation.score_caps.engagement_cap}
                onChange={(v) => patchScoreCaps({ engagement_cap: v })}
              />
            </div>
          </div>
        )
      case "score_triggers":
        return (
          <div>
            <div className="mb-3 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupScoreTriggers")}
            </div>
            <div className="flex flex-wrap gap-3.5">
              <CompactRatioField
                id="rt-trigger-strong-pos"
                suffix="%"
                label={t("configurations.editor.reportThresholds.triggerStrongPosLabel")}
                value={value.recommendation.score_triggers.strong_pos}
                onChange={(v) => patchScoreTriggers({ strong_pos: v })}
              />
              <CompactRatioField
                id="rt-trigger-strong-crit"
                suffix="%"
                label={t("configurations.editor.reportThresholds.triggerStrongCritLabel")}
                value={value.recommendation.score_triggers.strong_crit_max}
                onChange={(v) => patchScoreTriggers({ strong_crit_max: v })}
              />
              <CompactRatioField
                id="rt-trigger-weak-pos"
                suffix="%"
                label={t("configurations.editor.reportThresholds.triggerWeakPosLabel")}
                value={value.recommendation.score_triggers.weak_pos_max}
                onChange={(v) => patchScoreTriggers({ weak_pos_max: v })}
              />
              <CompactRatioField
                id="rt-trigger-crit-baseline"
                suffix="%"
                label={t("configurations.editor.reportThresholds.triggerCritBaselineLabel")}
                value={value.recommendation.score_triggers.crit_baseline}
                onChange={(v) => patchScoreTriggers({ crit_baseline: v })}
              />
            </div>
          </div>
        )
      case "takeaway":
        return (
          <div>
            <div className="mb-0.5 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupTakeaway")}
            </div>
            <span className="mb-2.5 block text-[11.5px] text-muted-foreground">
              {t("configurations.editor.reportThresholds.groupTakeawayHint")}
            </span>
            <div className="flex flex-wrap gap-3.5">
              <CompactRatioField
                id="rt-takeaway-pos-strong"
                suffix="%"
                label={t("configurations.editor.reportThresholds.takeawayPosStrongLabel")}
                value={value.takeaway.positive_strong}
                onChange={(v) => patchTakeaway({ positive_strong: v })}
              />
              <CompactRatioField
                id="rt-takeaway-pos-weak"
                suffix="%"
                label={t("configurations.editor.reportThresholds.takeawayPosWeakLabel")}
                value={value.takeaway.positive_weak}
                onChange={(v) => patchTakeaway({ positive_weak: v })}
              />
              <CompactRatioField
                id="rt-takeaway-crit-high"
                suffix="%"
                label={t("configurations.editor.reportThresholds.takeawayCritHighLabel")}
                value={value.takeaway.critical_high}
                onChange={(v) => patchTakeaway({ critical_high: v })}
              />
              <CompactRatioField
                id="rt-takeaway-contrast-gap"
                suffix="pp"
                label={t("configurations.editor.reportThresholds.takeawayContrastGapLabel")}
                value={value.takeaway.segment_contrast_gap}
                onChange={(v) => patchTakeaway({ segment_contrast_gap: v })}
              />
            </div>
          </div>
        )
      case "narrative":
        return (
          <div>
            <div className="mb-3 text-[0.95rem] font-semibold">
              {t("configurations.editor.reportThresholds.groupNarrative")}
            </div>
            <div className="flex flex-wrap gap-3.5">
              <CompactRatioField
                id="rt-narr-good-reception"
                suffix="%"
                label={t("configurations.editor.reportThresholds.narrGoodReceptionLabel")}
                value={value.recommendation.narrative.good_reception_pos}
                onChange={(v) => patchNarrative({ good_reception_pos: v })}
              />
              <CompactRatioField
                id="rt-narr-high-crit"
                suffix="%"
                label={t("configurations.editor.reportThresholds.narrHighCritLabel")}
                value={value.recommendation.narrative.high_crit}
                onChange={(v) => patchNarrative({ high_crit: v })}
              />
              <CompactRatioField
                id="rt-narr-segment-pos"
                suffix="%"
                label={t("configurations.editor.reportThresholds.narrSegmentPosLabel")}
                value={value.recommendation.narrative.segment_pos}
                onChange={(v) => patchNarrative({ segment_pos: v })}
              />
              <CompactRatioField
                id="rt-narr-segment-crit"
                suffix="%"
                label={t("configurations.editor.reportThresholds.narrSegmentCritLabel")}
                value={value.recommendation.narrative.segment_crit}
                onChange={(v) => patchNarrative({ segment_crit: v })}
              />
            </div>
          </div>
        )
      default: {
        const exhaustive: never = id
        return exhaustive
      }
    }
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-7">
      <div className="flex items-center justify-between gap-3">
        <p className="m-0 max-w-[520px] text-[12.5px] text-muted-foreground">
          {t("configurations.editor.sensitivityIntro")}
        </p>
        <button
          type="button"
          className="shrink-0 rounded-[var(--radius-sm)] border-[1.5px] border-[color:var(--border-hairline)] bg-white px-3.5 py-[7px] text-xs text-[color:var(--text-body)]"
          onClick={resetDefaults}
        >
          {t("configurations.editor.resetAllDefaults")}
        </button>
      </div>

      {validationKey ? (
        <p className="text-sm text-destructive">{t(validationKey)}</p>
      ) : null}

      <div className="flex items-start gap-7">
        <nav className="flex w-[210px] shrink-0 flex-col gap-0.5">
          <div className="mb-0.5 px-2 py-1 text-[10.5px] font-bold uppercase tracking-[0.05em] text-muted-foreground">
            {t("configurations.editor.sensitivityBasic")}
          </div>
          {BASIC_GROUPS.map((group) => (
            <GroupNavButton
              key={group.id}
              label={t(group.labelKey)}
              selected={groupId === group.id}
              onSelect={() => setGroupId(group.id)}
            />
          ))}
          <div className="px-2 pb-0.5 pt-3.5 text-[10.5px] font-bold uppercase tracking-[0.05em] text-muted-foreground">
            {t("configurations.editor.sensitivityAdvanced")}
          </div>
          {ADVANCED_GROUPS.map((group) => (
            <GroupNavButton
              key={group.id}
              label={t(group.labelKey)}
              selected={groupId === group.id}
              onSelect={() => setGroupId(group.id)}
            />
          ))}
        </nav>
        <div className="min-w-0 flex-1 rounded-[var(--radius-lg)] border border-[color:var(--border-hairline)] px-[26px] py-[22px]">
          {isAdvanced ? (
            <p className="mb-4 text-xs text-[color:var(--db-error)]">
              {t("configurations.editor.reportThresholds.advancedWarning")}
            </p>
          ) : null}
          {renderGroup(groupId)}
        </div>
      </div>
    </div>
  )
}
