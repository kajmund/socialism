"""Jev decisions on materialized graph frontiers, never inside a transaction."""

import json
from dataclasses import dataclass

from app.config import settings
from app.jev.system import HttpJevSystemOne, JevClientError, JevSystemOne, parse_noul
from app.services.research.fast_controller import research_jev_model
from app.services.research.models import ResearchNeed
from app.services.research.result_store import SavedResearch


@dataclass(frozen=True)
class Coverage:
    outcome: str
    confidence: float
    model: str


class ResultJudge:
    def __init__(self, prompts: dict[str, str], client: JevSystemOne | None = None) -> None:
        self.navigation = json.loads(prompts["research.result_navigation"])
        self.coverage = json.loads(prompts["research.result_coverage"])
        self.client = client or HttpJevSystemOne()

    async def navigate(self, need: ResearchNeed, context: dict, edges: list[dict]) -> set[str]:
        result = await self.client.ask(
            state={"requested_question": need.question, "context": context, "edges": edges},
            questions={
                edge["id"]: {
                    **self.navigation,
                    "instructions": self.navigation["instructions"] + " Edge ID: " + edge["id"],
                }
                for edge in edges
            },
            model=research_jev_model(),
            timeout_seconds=settings.jev_timeout_seconds,
        )
        # Only a confident negative prunes an edge; uncertainty keeps it explorable.
        return {edge["id"] for edge in edges if parse_noul(result.answers, edge["id"]) > 0.1}

    async def covers(self, need: ResearchNeed, context: dict, candidate: SavedResearch) -> Coverage:
        state = {
            "requested_question": need.question,
            "requested_context": context,
            "source_types": need.source_types,
            "domains": need.domains,
            "modalities": need.modalities,
            "capabilities": need.capabilities,
            "saved_question": candidate.question,
            "saved_context": candidate.context,
            "assessment": candidate.assessment,
            "source_types_in_basis": sorted({item.source_type for item in candidate.basis}),
            "evidence_count": len(candidate.basis),
        }
        # Never turn truncated evidence into a claim of full coverage.
        if len(json.dumps(state, ensure_ascii=False)) > settings.research_jev_max_state_chars:
            return Coverage("PARTIAL", 0.0, research_jev_model())
        result = await self.client.ask(
            state=state,
            questions={"coverage": self.coverage},
            model=research_jev_model(),
            timeout_seconds=settings.jev_timeout_seconds,
        )
        answer = result.answers.get("coverage", {})
        choice = answer.get("choice")
        confidence = answer.get("confidence")
        if (
            choice not in {"FULL", "PARTIAL", "NONE"}
            or type(confidence) not in (float, int)
            or not 0 <= confidence <= 1
        ):
            raise JevClientError(
                "Invalid saved research coverage decision", category="schema_validation"
            )
        return Coverage(choice, float(confidence), result.model)
