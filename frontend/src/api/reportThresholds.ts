/** Mirrors backend `app/services/report/thresholds.py` defaults — keep in sync. */

export type VerdictThresholds = {
  pos_strong: number
  pos_mixed: number
  crit_weak: number
}

export type DiffThresholds = {
  clear: number
  weak: number
}

export type ScoreWeights = {
  positive: number
  critical_headroom: number
  injection_likes: number
  engagement: number
}

export type ScoreCaps = {
  zero_likes_max: number
  strong_floor: number
  weak_ceiling: number
  injection_likes_cap: number
  engagement_cap: number
}

export type ScoreTriggers = {
  strong_pos: number
  strong_crit_max: number
  weak_pos_max: number
  crit_baseline: number
}

export type ActionBands = {
  ready: number
  minor_adjust: number
  revise: number
}

export type NarrativeThresholds = {
  good_reception_pos: number
  high_crit: number
  segment_pos: number
  segment_crit: number
}

export type TakeawayThresholds = {
  positive_strong: number
  positive_weak: number
  critical_high: number
  segment_contrast_gap: number
}

export type RecommendationThresholds = {
  score_weights: ScoreWeights
  score_caps: ScoreCaps
  score_triggers: ScoreTriggers
  action_bands: ActionBands
  narrative: NarrativeThresholds
}

export type ReportThresholds = {
  verdict: VerdictThresholds
  diff: DiffThresholds
  topic_drift: number
  takeaway: TakeawayThresholds
  recommendation: RecommendationThresholds
}

export const DEFAULT_REPORT_THRESHOLDS: ReportThresholds = {
  verdict: {
    pos_strong: 0.5,
    pos_mixed: 0.3,
    crit_weak: 0.5,
  },
  diff: {
    clear: 0.08,
    weak: 0.03,
  },
  topic_drift: 0.1,
  takeaway: {
    positive_strong: 0.4,
    positive_weak: 0.28,
    critical_high: 0.42,
    segment_contrast_gap: 0.12,
  },
  recommendation: {
    score_weights: {
      positive: 45,
      critical_headroom: 25,
      injection_likes: 15,
      engagement: 15,
    },
    score_caps: {
      zero_likes_max: 15,
      strong_floor: 65,
      weak_ceiling: 45,
      injection_likes_cap: 20,
      engagement_cap: 80,
    },
    score_triggers: {
      strong_pos: 0.45,
      strong_crit_max: 0.45,
      weak_pos_max: 0.25,
      crit_baseline: 0.35,
    },
    action_bands: {
      ready: 75,
      minor_adjust: 55,
      revise: 35,
    },
    narrative: {
      good_reception_pos: 0.35,
      high_crit: 0.45,
      segment_pos: 0.45,
      segment_crit: 0.5,
    },
  },
}

export function cloneReportThresholds(thresholds: ReportThresholds): ReportThresholds {
  return structuredClone(thresholds)
}

/** Merge API payload with defaults (e.g. new takeaway keys on older stored configs). */
export function mergeReportThresholds(
  raw: Partial<ReportThresholds> | ReportThresholds,
): ReportThresholds {
  const base = DEFAULT_REPORT_THRESHOLDS
  return {
    verdict: { ...base.verdict, ...raw.verdict },
    diff: { ...base.diff, ...raw.diff },
    topic_drift: raw.topic_drift ?? base.topic_drift,
    takeaway: { ...base.takeaway, ...raw.takeaway },
    recommendation: {
      score_weights: {
        ...base.recommendation.score_weights,
        ...raw.recommendation?.score_weights,
      },
      score_caps: {
        ...base.recommendation.score_caps,
        ...raw.recommendation?.score_caps,
      },
      score_triggers: {
        ...base.recommendation.score_triggers,
        ...raw.recommendation?.score_triggers,
      },
      action_bands: {
        ...base.recommendation.action_bands,
        ...raw.recommendation?.action_bands,
      },
      narrative: {
        ...base.recommendation.narrative,
        ...raw.recommendation?.narrative,
      },
    },
  }
}

export type ReportThresholdValidationKey =
  | "configurations.editor.reportThresholds.validation.verdictOrder"
  | "configurations.editor.reportThresholds.validation.diffOrder"
  | "configurations.editor.reportThresholds.validation.takeawayOrder"
  | "configurations.editor.reportThresholds.validation.actionBandsOrder"

export function reportThresholdValidationKey(
  thresholds: ReportThresholds,
): ReportThresholdValidationKey | null {
  const { verdict, diff, takeaway, recommendation } = thresholds
  if (verdict.pos_mixed >= verdict.pos_strong) {
    return "configurations.editor.reportThresholds.validation.verdictOrder"
  }
  if (diff.weak >= diff.clear) {
    return "configurations.editor.reportThresholds.validation.diffOrder"
  }
  if (takeaway.positive_weak >= takeaway.positive_strong) {
    return "configurations.editor.reportThresholds.validation.takeawayOrder"
  }
  const bands = recommendation.action_bands
  if (!(bands.revise < bands.minor_adjust && bands.minor_adjust < bands.ready)) {
    return "configurations.editor.reportThresholds.validation.actionBandsOrder"
  }
  return null
}
