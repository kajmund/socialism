import { useState } from "react"
import {
  DEFAULT_REPORT_THRESHOLDS,
  cloneReportThresholds,
  type ReportThresholds,
} from "@/api/reportThresholds"
import { AdminButton } from "@/components/ui/admin-button"
import { useLocale, type MessageKey } from "@/i18n"

type ReportThresholdsEditorProps = {
  value: ReportThresholds
  onChange: (next: ReportThresholds) => void
  validationKey: MessageKey | null
}

type RatioFieldProps = {
  label: string
  hint?: string
  value: number
  onChange: (ratio: number) => void
  id: string
}

type IntegerFieldProps = {
  label: string
  hint?: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  step?: number
  id: string
}

type FloatFieldProps = {
  label: string
  hint?: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  step?: number
  id: string
}

function ratioToPercent(ratio: number): number {
  return Math.round(ratio * 1000) / 10
}

function percentToRatio(percent: number): number {
  return percent / 100
}

function ratioToPoints(ratio: number): number {
  return Math.round(ratio * 1000) / 10
}

function pointsToRatio(points: number): number {
  return points / 100
}

function RatioPercentField({ label, hint, value, onChange, id }: RatioFieldProps) {
  return (
    <label htmlFor={id} className="block space-y-1">
      <span className="text-sm">{label}</span>
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="number"
          min={0}
          max={100}
          step={0.1}
          className="w-28 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
          value={ratioToPercent(value)}
          onChange={(e) => onChange(percentToRatio(Number(e.target.value)))}
        />
        <span className="text-xs text-muted-foreground">%</span>
      </div>
    </label>
  )
}

function PointsField({ label, hint, value, onChange, id }: RatioFieldProps) {
  return (
    <label htmlFor={id} className="block space-y-1">
      <span className="text-sm">{label}</span>
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="number"
          min={0}
          max={100}
          step={0.1}
          className="w-28 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
          value={ratioToPoints(value)}
          onChange={(e) => onChange(pointsToRatio(Number(e.target.value)))}
        />
        <span className="text-xs text-muted-foreground">pp</span>
      </div>
    </label>
  )
}

function IntegerScoreField({
  label,
  hint,
  value,
  onChange,
  min,
  max,
  step = 1,
  id,
}: IntegerFieldProps) {
  return (
    <label htmlFor={id} className="block space-y-1">
      <span className="text-sm">{label}</span>
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        className="w-28 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function FloatWeightField({
  label,
  hint,
  value,
  onChange,
  min,
  max,
  step = 1,
  id,
}: FloatFieldProps) {
  return (
    <label htmlFor={id} className="block space-y-1">
      <span className="text-sm">{label}</span>
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        className="w-28 rounded-md border border-[color:var(--border-hairline)] bg-db-ink-0 px-3 py-2 font-mono text-sm"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

export function ReportThresholdsEditor({
  value,
  onChange,
  validationKey,
}: ReportThresholdsEditorProps) {
  const { t } = useLocale()
  const [advancedOpen, setAdvancedOpen] = useState(false)

  function patchVerdict(patch: Partial<ReportThresholds["verdict"]>) {
    onChange({
      ...value,
      verdict: { ...value.verdict, ...patch },
    })
  }

  function patchDiff(patch: Partial<ReportThresholds["diff"]>) {
    onChange({
      ...value,
      diff: { ...value.diff, ...patch },
    })
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
    onChange({
      ...value,
      takeaway: { ...value.takeaway, ...patch },
    })
  }

  return (
    <fieldset className="space-y-5 rounded border p-4">
      <legend className="px-1 text-sm font-medium">
        {t("configurations.editor.reportThresholds.title")}
      </legend>

      <p className="text-xs text-muted-foreground">
        {t("configurations.editor.reportThresholds.intro")}
      </p>

      <AdminButton
        type="button"
        variant="secondary"
        onClick={() => onChange(cloneReportThresholds(DEFAULT_REPORT_THRESHOLDS))}
      >
        {t("configurations.editor.reportThresholds.resetDefaults")}
      </AdminButton>

      {validationKey ? (
        <p className="text-sm text-destructive">{t(validationKey)}</p>
      ) : null}

      <fieldset className="space-y-4 rounded border border-[color:var(--border-hairline)] p-4">
        <legend className="px-1 text-sm font-medium">
          {t("configurations.editor.reportThresholds.groupVerdict")}
        </legend>
        <p className="text-xs text-muted-foreground">
          {t("configurations.editor.reportThresholds.groupVerdictHint")}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <RatioPercentField
            id="rt-pos-strong"
            label={t("configurations.editor.reportThresholds.posStrongLabel")}
            hint={t("configurations.editor.reportThresholds.posStrongHint")}
            value={value.verdict.pos_strong}
            onChange={(v) => patchVerdict({ pos_strong: v })}
          />
          <RatioPercentField
            id="rt-pos-mixed"
            label={t("configurations.editor.reportThresholds.posMixedLabel")}
            hint={t("configurations.editor.reportThresholds.posMixedHint")}
            value={value.verdict.pos_mixed}
            onChange={(v) => patchVerdict({ pos_mixed: v })}
          />
          <RatioPercentField
            id="rt-crit-weak"
            label={t("configurations.editor.reportThresholds.critWeakLabel")}
            hint={t("configurations.editor.reportThresholds.critWeakHint")}
            value={value.verdict.crit_weak}
            onChange={(v) => patchVerdict({ crit_weak: v })}
          />
        </div>
      </fieldset>

      <fieldset className="space-y-4 rounded border border-[color:var(--border-hairline)] p-4">
        <legend className="px-1 text-sm font-medium">
          {t("configurations.editor.reportThresholds.groupDiff")}
        </legend>
        <p className="text-xs text-muted-foreground">
          {t("configurations.editor.reportThresholds.groupDiffHint")}
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <PointsField
            id="rt-diff-clear"
            label={t("configurations.editor.reportThresholds.diffClearLabel")}
            hint={t("configurations.editor.reportThresholds.diffClearHint")}
            value={value.diff.clear}
            onChange={(v) => patchDiff({ clear: v })}
          />
          <PointsField
            id="rt-diff-weak"
            label={t("configurations.editor.reportThresholds.diffWeakLabel")}
            hint={t("configurations.editor.reportThresholds.diffWeakHint")}
            value={value.diff.weak}
            onChange={(v) => patchDiff({ weak: v })}
          />
          <RatioPercentField
            id="rt-topic-drift"
            label={t("configurations.editor.reportThresholds.topicDriftLabel")}
            hint={t("configurations.editor.reportThresholds.topicDriftHint")}
            value={value.topic_drift}
            onChange={(v) => onChange({ ...value, topic_drift: v })}
          />
        </div>
      </fieldset>

      <fieldset className="space-y-4 rounded border border-[color:var(--border-hairline)] p-4">
        <legend className="px-1 text-sm font-medium">
          {t("configurations.editor.reportThresholds.groupActionBands")}
        </legend>
        <p className="text-xs text-muted-foreground">
          {t("configurations.editor.reportThresholds.groupActionBandsHint")}
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          <IntegerScoreField
            id="rt-ready"
            label={t("configurations.editor.reportThresholds.actionReadyLabel")}
            hint={t("configurations.editor.reportThresholds.actionReadyHint")}
            min={0}
            max={100}
            value={value.recommendation.action_bands.ready}
            onChange={(v) => patchActionBands({ ready: v })}
          />
          <IntegerScoreField
            id="rt-minor-adjust"
            label={t("configurations.editor.reportThresholds.actionMinorAdjustLabel")}
            hint={t("configurations.editor.reportThresholds.actionMinorAdjustHint")}
            min={0}
            max={100}
            value={value.recommendation.action_bands.minor_adjust}
            onChange={(v) => patchActionBands({ minor_adjust: v })}
          />
          <IntegerScoreField
            id="rt-revise"
            label={t("configurations.editor.reportThresholds.actionReviseLabel")}
            hint={t("configurations.editor.reportThresholds.actionReviseHint")}
            min={0}
            max={100}
            value={value.recommendation.action_bands.revise}
            onChange={(v) => patchActionBands({ revise: v })}
          />
        </div>
      </fieldset>

      <div className="rounded border border-[color:var(--border-hairline)]">
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          {t("configurations.editor.reportThresholds.advancedToggle")}
          <span aria-hidden="true">{advancedOpen ? "−" : "+"}</span>
        </button>
        {advancedOpen ? (
          <div className="space-y-5 border-t border-[color:var(--border-hairline)] p-4">
            <p className="text-xs text-destructive">
              {t("configurations.editor.reportThresholds.advancedWarning")}
            </p>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">
                {t("configurations.editor.reportThresholds.groupScoreWeights")}
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <FloatWeightField
                  id="rt-weight-positive"
                  label={t("configurations.editor.reportThresholds.weightPositiveLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_weights.positive}
                  onChange={(v) => patchScoreWeights({ positive: v })}
                />
                <FloatWeightField
                  id="rt-weight-critical"
                  label={t("configurations.editor.reportThresholds.weightCriticalLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_weights.critical_headroom}
                  onChange={(v) => patchScoreWeights({ critical_headroom: v })}
                />
                <FloatWeightField
                  id="rt-weight-likes"
                  label={t("configurations.editor.reportThresholds.weightLikesLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_weights.injection_likes}
                  onChange={(v) => patchScoreWeights({ injection_likes: v })}
                />
                <FloatWeightField
                  id="rt-weight-engagement"
                  label={t("configurations.editor.reportThresholds.weightEngagementLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_weights.engagement}
                  onChange={(v) => patchScoreWeights({ engagement: v })}
                />
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">
                {t("configurations.editor.reportThresholds.groupScoreCaps")}
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <FloatWeightField
                  id="rt-cap-zero-likes"
                  label={t("configurations.editor.reportThresholds.capZeroLikesLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_caps.zero_likes_max}
                  onChange={(v) => patchScoreCaps({ zero_likes_max: v })}
                />
                <FloatWeightField
                  id="rt-cap-strong-floor"
                  label={t("configurations.editor.reportThresholds.capStrongFloorLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_caps.strong_floor}
                  onChange={(v) => patchScoreCaps({ strong_floor: v })}
                />
                <FloatWeightField
                  id="rt-cap-weak-ceiling"
                  label={t("configurations.editor.reportThresholds.capWeakCeilingLabel")}
                  min={0}
                  max={100}
                  value={value.recommendation.score_caps.weak_ceiling}
                  onChange={(v) => patchScoreCaps({ weak_ceiling: v })}
                />
                <IntegerScoreField
                  id="rt-cap-likes"
                  label={t("configurations.editor.reportThresholds.capLikesLabel")}
                  min={1}
                  max={999}
                  value={value.recommendation.score_caps.injection_likes_cap}
                  onChange={(v) => patchScoreCaps({ injection_likes_cap: v })}
                />
                <IntegerScoreField
                  id="rt-cap-engagement"
                  label={t("configurations.editor.reportThresholds.capEngagementLabel")}
                  min={1}
                  max={999}
                  value={value.recommendation.score_caps.engagement_cap}
                  onChange={(v) => patchScoreCaps({ engagement_cap: v })}
                />
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">
                {t("configurations.editor.reportThresholds.groupScoreTriggers")}
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <RatioPercentField
                  id="rt-trigger-strong-pos"
                  label={t("configurations.editor.reportThresholds.triggerStrongPosLabel")}
                  hint={t("configurations.editor.reportThresholds.triggerStrongPosHint")}
                  value={value.recommendation.score_triggers.strong_pos}
                  onChange={(v) => patchScoreTriggers({ strong_pos: v })}
                />
                <RatioPercentField
                  id="rt-trigger-strong-crit"
                  label={t("configurations.editor.reportThresholds.triggerStrongCritLabel")}
                  value={value.recommendation.score_triggers.strong_crit_max}
                  onChange={(v) => patchScoreTriggers({ strong_crit_max: v })}
                />
                <RatioPercentField
                  id="rt-trigger-weak-pos"
                  label={t("configurations.editor.reportThresholds.triggerWeakPosLabel")}
                  value={value.recommendation.score_triggers.weak_pos_max}
                  onChange={(v) => patchScoreTriggers({ weak_pos_max: v })}
                />
                <RatioPercentField
                  id="rt-trigger-crit-baseline"
                  label={t("configurations.editor.reportThresholds.triggerCritBaselineLabel")}
                  value={value.recommendation.score_triggers.crit_baseline}
                  onChange={(v) => patchScoreTriggers({ crit_baseline: v })}
                />
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">
                {t("configurations.editor.reportThresholds.groupTakeaway")}
              </h3>
              <p className="text-xs text-muted-foreground">
                {t("configurations.editor.reportThresholds.groupTakeawayHint")}
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                <RatioPercentField
                  id="rt-takeaway-pos-strong"
                  label={t("configurations.editor.reportThresholds.takeawayPosStrongLabel")}
                  hint={t("configurations.editor.reportThresholds.takeawayPosStrongHint")}
                  value={value.takeaway.positive_strong}
                  onChange={(v) => patchTakeaway({ positive_strong: v })}
                />
                <RatioPercentField
                  id="rt-takeaway-pos-weak"
                  label={t("configurations.editor.reportThresholds.takeawayPosWeakLabel")}
                  hint={t("configurations.editor.reportThresholds.takeawayPosWeakHint")}
                  value={value.takeaway.positive_weak}
                  onChange={(v) => patchTakeaway({ positive_weak: v })}
                />
                <RatioPercentField
                  id="rt-takeaway-crit-high"
                  label={t("configurations.editor.reportThresholds.takeawayCritHighLabel")}
                  hint={t("configurations.editor.reportThresholds.takeawayCritHighHint")}
                  value={value.takeaway.critical_high}
                  onChange={(v) => patchTakeaway({ critical_high: v })}
                />
                <PointsField
                  id="rt-takeaway-contrast-gap"
                  label={t("configurations.editor.reportThresholds.takeawayContrastGapLabel")}
                  hint={t("configurations.editor.reportThresholds.takeawayContrastGapHint")}
                  value={value.takeaway.segment_contrast_gap}
                  onChange={(v) => patchTakeaway({ segment_contrast_gap: v })}
                />
              </div>
            </div>

            <div className="space-y-3">
              <h3 className="text-sm font-medium">
                {t("configurations.editor.reportThresholds.groupNarrative")}
              </h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <RatioPercentField
                  id="rt-narr-good-reception"
                  label={t("configurations.editor.reportThresholds.narrGoodReceptionLabel")}
                  value={value.recommendation.narrative.good_reception_pos}
                  onChange={(v) => patchNarrative({ good_reception_pos: v })}
                />
                <RatioPercentField
                  id="rt-narr-high-crit"
                  label={t("configurations.editor.reportThresholds.narrHighCritLabel")}
                  value={value.recommendation.narrative.high_crit}
                  onChange={(v) => patchNarrative({ high_crit: v })}
                />
                <RatioPercentField
                  id="rt-narr-segment-pos"
                  label={t("configurations.editor.reportThresholds.narrSegmentPosLabel")}
                  value={value.recommendation.narrative.segment_pos}
                  onChange={(v) => patchNarrative({ segment_pos: v })}
                />
                <RatioPercentField
                  id="rt-narr-segment-crit"
                  label={t("configurations.editor.reportThresholds.narrSegmentCritLabel")}
                  value={value.recommendation.narrative.segment_crit}
                  onChange={(v) => patchNarrative({ segment_crit: v })}
                />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </fieldset>
  )
}
