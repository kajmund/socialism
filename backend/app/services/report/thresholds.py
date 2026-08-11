"""Snabbrapport verdict and recommendation thresholds (configuration-backed)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class VerdictThresholds(BaseModel):
    pos_strong: float = Field(default=0.50, ge=0.0, le=1.0)
    pos_mixed: float = Field(default=0.30, ge=0.0, le=1.0)
    crit_weak: float = Field(default=0.50, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_order(self) -> VerdictThresholds:
        if self.pos_mixed >= self.pos_strong:
            raise ValueError("verdict.pos_mixed must be < verdict.pos_strong")
        return self


class DiffThresholds(BaseModel):
    clear: float = Field(default=0.08, ge=0.0, le=1.0)
    weak: float = Field(default=0.03, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_order(self) -> DiffThresholds:
        if self.weak >= self.clear:
            raise ValueError("diff.weak must be < diff.clear")
        return self


class ScoreWeights(BaseModel):
    positive: float = Field(default=45.0, ge=0.0)
    critical_headroom: float = Field(default=25.0, ge=0.0)
    injection_likes: float = Field(default=15.0, ge=0.0)
    engagement: float = Field(default=15.0, ge=0.0)


class ScoreCaps(BaseModel):
    zero_likes_max: float = Field(default=15.0, ge=0.0, le=100.0)
    strong_floor: float = Field(default=65.0, ge=0.0, le=100.0)
    weak_ceiling: float = Field(default=45.0, ge=0.0, le=100.0)
    injection_likes_cap: int = Field(default=20, ge=1)
    engagement_cap: int = Field(default=80, ge=1)


class ScoreTriggers(BaseModel):
    strong_pos: float = Field(default=0.45, ge=0.0, le=1.0)
    strong_crit_max: float = Field(default=0.45, ge=0.0, le=1.0)
    weak_pos_max: float = Field(default=0.25, ge=0.0, le=1.0)
    crit_baseline: float = Field(default=0.35, ge=0.0, le=1.0)


class ActionBands(BaseModel):
    ready: int = Field(default=75, ge=0, le=100)
    minor_adjust: int = Field(default=55, ge=0, le=100)
    revise: int = Field(default=35, ge=0, le=100)

    @model_validator(mode="after")
    def _check_order(self) -> ActionBands:
        if not (self.revise < self.minor_adjust < self.ready):
            raise ValueError(
                "action_bands must satisfy revise < minor_adjust < ready"
            )
        return self


class NarrativeThresholds(BaseModel):
    good_reception_pos: float = Field(default=0.35, ge=0.0, le=1.0)
    high_crit: float = Field(default=0.45, ge=0.0, le=1.0)
    segment_pos: float = Field(default=0.45, ge=0.0, le=1.0)
    segment_crit: float = Field(default=0.50, ge=0.0, le=1.0)


class TakeawayThresholds(BaseModel):
    """Rule-based audience takeaway paragraphs (separate from verdict/narrative)."""

    positive_strong: float = Field(default=0.40, ge=0.0, le=1.0)
    positive_weak: float = Field(default=0.28, ge=0.0, le=1.0)
    critical_high: float = Field(default=0.42, ge=0.0, le=1.0)
    segment_contrast_gap: float = Field(default=0.12, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_order(self) -> TakeawayThresholds:
        if self.positive_weak >= self.positive_strong:
            raise ValueError(
                "takeaway.positive_weak must be < takeaway.positive_strong"
            )
        return self


class RecommendationThresholds(BaseModel):
    score_weights: ScoreWeights = Field(default_factory=ScoreWeights)
    score_caps: ScoreCaps = Field(default_factory=ScoreCaps)
    score_triggers: ScoreTriggers = Field(default_factory=ScoreTriggers)
    action_bands: ActionBands = Field(default_factory=ActionBands)
    narrative: NarrativeThresholds = Field(default_factory=NarrativeThresholds)


class ReportThresholds(BaseModel):
    verdict: VerdictThresholds = Field(default_factory=VerdictThresholds)
    diff: DiffThresholds = Field(default_factory=DiffThresholds)
    topic_drift: float = Field(default=0.10, ge=0.0, le=1.0)
    takeaway: TakeawayThresholds = Field(default_factory=TakeawayThresholds)
    recommendation: RecommendationThresholds = Field(
        default_factory=RecommendationThresholds
    )


def default_report_thresholds() -> ReportThresholds:
    return ReportThresholds()


def normalize_report_thresholds(raw: dict[str, Any] | None) -> ReportThresholds:
    """Parse stored JSON; fail loud on invalid shape (no silent partial merge)."""
    if not raw:
        return default_report_thresholds()
    return ReportThresholds.model_validate(raw)


def report_thresholds_to_dict(thresholds: ReportThresholds) -> dict[str, Any]:
    return thresholds.model_dump(mode="json")
