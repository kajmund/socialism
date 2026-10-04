"""Retrieve externally only after the supplied question's Graph basis was assessed."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.research.assessment import ResearchAssessor
from app.services.research.graph_reuse import log_external_search
from app.services.research.models import ResearchContext, ResearchEvidence, ResearchNeed
from app.services.research.question_reuse import merge_reused_with_provider
from app.services.research.reuse_gate import answer_is_sufficient, assess_reuse, fresh_evidence
from app.services.research.router import ResearchRouter
from app.services.research.question_graph import QuestionEvidenceGraph
from app.services.research.question_prepare import prepare_public_writeback


@dataclass(frozen=True)
class NeedReusePolicy:
    assessor: ResearchAssessor
    graph: QuestionEvidenceGraph


async def candidates_then_providers(
    *,
    factory: async_sessionmaker[AsyncSession],
    need: ResearchNeed,
    context: ResearchContext,
    router: ResearchRouter | None,
    router_factory,
    reused: list[ResearchEvidence],
    policy: NeedReusePolicy,
) -> list[ResearchEvidence]:
    from app.services.research.execution import _retrieve_need

    reused = fresh_evidence(reused)
    if reused and answer_is_sufficient(await assess_reuse(policy.assessor, need, reused)):
        return reused
    log_external_search(need, reused)
    provider = await _retrieve_need(
        factory=factory,
        need=need,
        context=context,
        router=router,
        router_factory=router_factory,
    )
    merged = merge_reused_with_provider(reused, provider)
    await prepare_public_writeback(factory, policy.graph, need, merged, context=context)
    return merged
