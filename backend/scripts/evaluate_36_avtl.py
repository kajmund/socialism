"""Live 36 § source-path and need-assessment evaluation in an isolated SQLite DB.

Run from backend with configured model credentials:
    uv run python -m scripts.evaluate_36_avtl --output /tmp/36-avtl.json
No production database reads or writes. No substituted model or fixture responses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.models import Kund
from app.llm.lagen_nu_selector import LlmLagenNuSelector
from app.llm.legal_question_validator import build_llm_legal_question_validator
from app.llm.legal_research import LlmLegalInterpreter
from app.llm.research_assessment import LlmResearchAssessor
from app.services.execution.service import (
    add_evidence_items,
    create_evidence_set,
    create_run,
    list_evidence_items,
)
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.knowledge.models import KnowledgeScope
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.question_validation import (
    MIXED_MD_AVTL_QUESTION,
    LegalNeedNormalizer,
    forbidden_retrieval_questions,
)
from app.services.lagen_nu.research_source import LagenNuResearchSource
from app.services.legal_research_result import LegalResearchResult
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.prompt_fields_store import ensure_prompt_field_defaults
from app.services.prompt_store import require_active_prompts
from app.services.research.assessment import sanitize_assessment_draft
from app.services.research.execution import assessable_from_item
from app.services.research.models import (
    ResearchContext,
    ResearchNeed,
    ResearchPlan,
    research_evidence,
)
from app.services.research_eval_harness import success_metrics

# The corpus under investigation is eval data, never provider dispatch logic.
CASES = [
    ("NJA 1987 s. 394", "swedish_case_law"),
    ("NJA 1992 s. 782", "swedish_case_law"),
    ("NJA 2009 s. 672", "swedish_case_law"),
    ("NJA 2002 s. 244", "swedish_case_law"),
    ("AD 1998 nr 109", "swedish_case_law"),
    ("SOU 1974:83", "swedish_preparatory_works"),
    ("NJA 2005 s. 142", "swedish_case_law"),
    ("prop. 1975/76:81", "swedish_preparatory_works"),
]


TOPICS = [
    (
        "Vilka typer av avtalsvillkor har faktiskt jämkats med stöd av 36 § avtalslagen i svensk rättspraxis?",
        "swedish_case_law",
    ),
    (
        "Vilka HD- eller hovrättsavgöranden har faktiskt beviljat jämkning enligt 36 § avtalslagen, och av vilka skäl?",
        "swedish_case_law",
    ),
    (
        "Vilka svenska rättsfall visar när jämkning enligt 36 § avtalslagen har nekats eller frågan lösts genom avtalstolkning?",
        "swedish_case_law",
    ),
    (
        "Vilka faktorer väger tyngst vid oskälighetsbedömningen enligt 36 § avtalslagen i kommersiella avtal?",
        "swedish_case_law",
    ),
    (
        "Vilka konsumentskyddshänsyn har varit avgörande i rättsfall om 36 § avtalslagen och konsumentavtal?",
        "swedish_case_law",
    ),
    (
        "Hur skiljer sig bedömningen enligt 36 § avtalslagen mellan olika avtalstyper enligt svensk rättspraxis?",
        "swedish_case_law",
    ),
    (
        "Vilket syfte och vilka bedömningsfaktorer för 36 § avtalslagen framgår av förarbetena?",
        "swedish_preparatory_works",
    ),
]


async def prepare_need_for_retrieval(
    need: ResearchNeed, normalizer: LegalNeedNormalizer
) -> list[ResearchNeed]:
    plan = await normalizer.normalize_plan(ResearchPlan(needs=[need]))
    blocked = forbidden_retrieval_questions([row.question for row in plan.needs])
    if blocked:
        raise ValueError(
            "incoherent institution/rule combination was sent to retrieval: "
            + blocked[0]
        )
    return plan.needs


async def evaluate(
    output: Path, *, input_artifacts: Path | None = None, mode: str = "sources"
) -> dict:
    captured_report = json.loads(input_artifacts.read_text()) if input_artifacts else None
    if captured_report is not None and captured_report.get("mode") != mode:
        raise ValueError("Captured evaluation mode does not match requested mode")
    captured = captured_report["evidence"] if captured_report is not None else None
    with TemporaryDirectory(prefix="research-36-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{directory}/eval.sqlite")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                customer = Kund(
                    name="Research eval", slug="research-eval", available_modules=["dd"]
                )
                session.add(customer)
                await ensure_prompt_field_defaults(session, "dd", PROMPT_FIELDS)
                await session.flush()
                run = await create_run(
                    session, customer_id=customer.id, module="dd", title="36 § evaluation"
                )
                evidence_set = await create_evidence_set(session, run_id=run.id)
                context = ResearchContext(
                    scope=KnowledgeScope(customer_id=customer.id, module="dd")
                )
                prompts = await require_active_prompts(
                    session, customer_id=customer.id, module="dd", language="sv"
                )
                validator = (
                    await build_llm_legal_question_validator(
                        session, customer_id=customer.id, module="dd"
                    )
                    if captured is None
                    else None
                )
                await session.commit()
            embeddings = OpenAIEmbeddingProvider.from_settings()
            vector_store = MemoryKnowledgeVectorStore()
            normalizer = LegalNeedNormalizer(validator) if validator is not None else None
            if normalizer is not None:
                mixed_check = await prepare_need_for_retrieval(
                    ResearchNeed(
                        id="mixed_md_avtl",
                        question=MIXED_MD_AVTL_QUESTION,
                        why_needed="Koherenskontroll av institution och rättsregel.",
                        source_types=["swedish_case_law"],
                    ),
                    normalizer,
                )
                if len(mixed_check) < 2:
                    raise ValueError("mixed MD/KO + 36 § AvtL question was not split")
            needs = []
            rows = []
            retrieval_questions = []
            for index, (citation, source_type) in enumerate(CASES if mode == "sources" else TOPICS):
                question = (
                    citation
                    if mode == "topics"
                    else (
                        f"Hur behandlas jämkning enligt 36 § avtalslagen i {citation}? "
                        + (
                            "Skilj partsyrkanden, underinstanser och avgörande domstols utfall."
                            if source_type == "swedish_case_law"
                            else "Ange föreslagen regel, tolkningsvägledning och begränsningar."
                        )
                    )
                )
                if (
                    captured_report is not None
                    and captured_report.get("questions", {}).get(f"source_{index + 1}") != question
                ):
                    raise ValueError("Captured question does not match current evaluation question")
                need = ResearchNeed(
                    id=f"source_{index + 1}",
                    question=question,
                    why_needed="Klassificera källans faktiska stöd för 36 §-researchen.",
                    source_types=[source_type],
                )
                needs.append(need)
                if captured is None:
                    assert normalizer is not None
                    runnable = await prepare_need_for_retrieval(need, normalizer)
                    retrieval_questions.extend(child.question for child in runnable)
                    found = []
                    for child in runnable:
                        async with factory() as research_session:
                            provider = LagenNuResearchSource(
                                source_type=source_type,
                                interpreter=LlmLegalInterpreter(session_factory=factory),
                                selector=LlmLagenNuSelector(session_factory=factory),
                                session=research_session,
                                embeddings=embeddings,
                                vector_store=vector_store,
                            )
                            found.extend(await provider.research(child, context))
                else:
                    blocked = forbidden_retrieval_questions([need.question])
                    if blocked:
                        raise ValueError(
                            "incoherent institution/rule combination was sent to retrieval: "
                            + blocked[0]
                        )
                    retrieval_questions.append(need.question)
                    found = []
                    for raw in captured:
                        if raw["research_need_id"] != need.id:
                            continue
                        payload = {key: value for key, value in raw.items() if key != "evidence_id"}
                        payload["retrieved_at"] = datetime.fromisoformat(raw["retrieved_at"])
                        if raw["legal_result"]:
                            payload["legal_result"] = LegalResearchResult.model_validate(
                                raw["legal_result"]
                            )
                        found.append(research_evidence(**payload))
                    if not found:
                        raise ValueError(f"Missing captured source results: {need.id}")
                rows.extend(found)
                print(
                    citation,
                    [(row.status, row.metadata.get("failure_category")) for row in found],
                    flush=True,
                )
                # Checkpoint measurements even if a later external request fails.
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(
                        {
                            "sources_completed": index + 1,
                            "mode": mode,
                            "questions": {need.id: need.question for need in needs},
                            "retrieval_questions": list(retrieval_questions),
                            "evidence": [
                                {
                                    **asdict(row),
                                    "retrieved_at": row.retrieved_at.isoformat(),
                                    "legal_result": row.legal_result.model_dump(mode="json")
                                    if row.legal_result
                                    else None,
                                }
                                for row in rows
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            async with factory() as session:
                await add_evidence_items(session, evidence_set_id=evidence_set.id, items=rows)
                evidence = [
                    assessable_from_item(item)
                    for item in await list_evidence_items(session, evidence_set.id)
                ]
            plan = ResearchPlan(needs=needs)
            assessor = LlmResearchAssessor(
                system_prompt=prompts["research.assessment.system"],
                user_prompt=prompts["research.assessment.user"],
                provider=settings.llm_provider,
                model=settings.selected_llm_model,
            )
            assessment = sanitize_assessment_draft(
                await assessor.assess(plan, evidence), plan=plan, evidence=evidence
            )
            report = json.loads(output.read_text())
            report.update(
                {
                    "model": settings.selected_llm_model,
                    "need_ids": [need.id for need in needs],
                    "questions": {need.id: need.question for need in needs},
                    "assessment": {
                        "needs": {
                            row.research_need_id: row.sufficient
                            for row in assessment.need_assessments
                        },
                        "details": asdict(assessment),
                    },
                }
            )
            report["metrics"] = success_metrics(report)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            return report
        finally:
            await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifacts",
        type=Path,
        help="Explicitly reassess a captured source run instead of retrieving again",
    )
    parser.add_argument("--mode", choices=["sources", "topics"], default="sources")
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.output, input_artifacts=args.artifacts, mode=args.mode))
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
