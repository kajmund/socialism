"""Opt-in complete-EvidenceSet assessor. Execution is WorkflowRunner only."""

from __future__ import annotations

from collections.abc import Sequence

from app.jev.system import JevSystemOne
from app.services.research.assessment import AssessableEvidence, ResearchAssessmentDraft
from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.narrative import NarrativeFn
from app.services.research.sufficiency_experiment.types import ExperimentConfig, ExperimentReport


async def run_experiment(
    plan: ResearchPlan,
    evidence: Sequence[AssessableEvidence],
    *,
    client: JevSystemOne,
    config: ExperimentConfig | None = None,
    narrative: NarrativeFn | None = None,
    live_measurement: str = "not_run",
) -> ExperimentReport:
    loop = SufficiencyLoop(
        plan,
        evidence,
        client=client,
        config=config or ExperimentConfig(),
        narrative=narrative,
        live_measurement=live_measurement,
    )
    await loop.run()
    if loop.report is None:
        raise RuntimeError("SufficiencyLoop finished without a report")
    return loop.report


class ExperimentResearchAssessor:
    """ResearchAssessor that never truncates the EvidenceSet."""

    def __init__(
        self,
        *,
        client: JevSystemOne,
        config: ExperimentConfig | None = None,
        narrative: NarrativeFn | None = None,
        live_measurement: str = "not_run",
    ) -> None:
        self._client = client
        self._config = config or ExperimentConfig()
        self._narrative = narrative
        self._live_measurement = live_measurement

    async def assess(
        self,
        plan: ResearchPlan,
        evidence: Sequence[AssessableEvidence],
    ) -> ResearchAssessmentDraft:
        report = await run_experiment(
            plan,
            evidence,
            client=self._client,
            config=self._config,
            narrative=self._narrative,
            live_measurement=self._live_measurement,
        )
        return report.draft
