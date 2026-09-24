"""Opt-in assessment regression using two public, independently checked court cases.

Run from backend with PYTHONPATH=. and configured DB/LLM/MCP access. First run
scripts/evaluate_legal_case_grounding.py to produce --case-report. No attempt writes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import app.services.execution  # noqa: F401 -- register execution ORM relationships
from app.config import settings
from app.database.session import SessionLocal, engine
from app.llm.research_assessment import LlmResearchAssessor
from app.services.lagen_nu.mcp_client import OfficialLagenNuMcpClient
from app.services.legal_research_result import LegalResearchResult
from app.services.prompt_store import require_active_prompts
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessmentDraft,
    ResearchAssessmentError,
    ResearchAssessor,
)
from app.services.research.models import ResearchNeed, ResearchPlan
from scripts.evaluate_legal_case_grounding import CASES, QUESTION, check_result


@dataclass(frozen=True)
class Scenario:
    name: str
    question: str
    case_ids: tuple[str, ...]
    sufficient: bool


SCENARIOS = (
    Scenario('open_positive', QUESTION, ('1999s408',), True),
    Scenario('open_negative', QUESTION, ('2010s467',), False),
    Scenario('open_mixed', QUESTION, ('1999s408', '2010s467'), True),
    Scenario('one_example', 'Ge ett belagt exempel; en uttömmande lista krävs inte. ' + QUESTION,
             ('1999s408', '2010s467'), True),
    Scenario('two_examples', 'Ge minst två olika belagda avgöranden. ' + QUESTION,
             ('1999s408', '2010s467'), False),
    Scenario('exhaustive', 'Ge en uttömmande förteckning och belägg att inga avgöranden saknas. ' + QUESTION,
             ('1999s408', '2010s467'), False),
)


def check_assessment(scenario: Scenario, draft: ResearchAssessmentDraft) -> dict[str, bool]:
    rows = draft.need_assessments
    row = rows[0] if len(rows) == 1 else None
    expected_support = {'1999s408'} if '1999s408' in scenario.case_ids else set()
    return {
        'overall_verdict': draft.result == ('sufficient' if scenario.sufficient else 'insufficient'),
        'need_verdict': row is not None and row.research_need_id == 'n1'
        and row.sufficient is scenario.sufficient,
        'support': row is not None and set(row.supporting_evidence_ids) == expected_support,
        'gap_consistency': row is not None and (
            not draft.gaps and not row.missing_or_weak and not row.further_information
            if scenario.sufficient else bool(row.missing_or_weak and row.further_information)
        ),
    }


async def load_evidence(report: dict, client: OfficialLagenNuMcpClient) -> dict[str, AssessableEvidence]:
    if report.get('question') != QUESTION or report.get('passed') is not True:
        raise ValueError('Requires a passing report for the public case-grounding question')
    rows = report.get('cases', [])
    expected = {'https://lagen.nu/dom/nja/' + case for case in CASES}
    if len(rows) != len(expected) or {row.get('source') for row in rows} != expected:
        raise ValueError('Case report must contain exactly the two public control cases')
    evidence = {}
    for row in rows:
        uri = row['source']
        case = uri.rsplit('/', 1)[1]
        document = await client.get_document(uri, max_chars=200000)
        digest = hashlib.sha256(document.text.encode()).hexdigest()
        if document.truncated or digest != row['sha256']:
            raise ValueError(f'Public source is truncated or changed: {uri}')
        legal = LegalResearchResult.model_validate({**row['analysis'], 'raw_text': document.text})
        if legal.source.canonical_uri != uri or not all(check_result(case, document.text, legal).values()):
            raise ValueError(f'Case analysis fails independent grounding checks: {uri}')
        evidence[case] = AssessableEvidence(
            evidence_id=case, research_need_id='n1', source_type='swedish_case_law',
            status='found', title=legal.source.title, excerpt=legal.case_law.citations[0].quote,
            locator=None, source_id=uri, source_url=uri, provider='lagen_nu', score=None,
            provenance={}, retrieved_at=datetime.now(UTC), content_hash=digest, legal_result=legal,
        )
    return evidence


async def evaluate_scenarios(
    assessor: ResearchAssessor, evidence: dict[str, AssessableEvidence], output: Path, *, repeats: int,
) -> bool:
    if repeats < 1:
        raise ValueError('repeats must be positive')
    rows = []
    for repeat in range(1, repeats + 1):
        for scenario in SCENARIOS:
            plan = ResearchPlan(needs=[ResearchNeed(
                id='n1', question=scenario.question,
                why_needed='Verifiera bedömning av stödjande och irrelevanta rättsfall.',
                source_types=['swedish_case_law'],
            )])
            started = time.perf_counter()
            row = {'scenario': scenario.name, 'repeat': repeat, 'question': scenario.question}
            try:
                draft = await assessor.assess(plan, [evidence[key] for key in scenario.case_ids])
                checks = check_assessment(scenario, draft)
                row.update(checks=checks, passed=all(checks.values()), assessment=asdict(draft))
            except ResearchAssessmentError as exc:
                row.update(passed=False, failure=str(exc))
            row['seconds'] = round(time.perf_counter() - started, 2)
            rows.append(row)
            output.write_text(json.dumps({
                'complete': len(rows) == len(SCENARIOS) * repeats,
                'passed': len(rows) == len(SCENARIOS) * repeats and all(r['passed'] for r in rows),
                'source_hashes': {key: item.content_hash for key, item in evidence.items()},
                'results': rows,
            }, ensure_ascii=False, indent=2))
            print(json.dumps({key: value for key, value in row.items() if key != 'assessment'}, ensure_ascii=False), flush=True)
    return all(row['passed'] for row in rows)


async def evaluate(customer_id: int, module: str, case_report: Path, output: Path, repeats: int) -> bool:
    client = OfficialLagenNuMcpClient()
    try:
        evidence = await load_evidence(json.loads(case_report.read_text()), client)
        async with SessionLocal() as session:
            prompts = await require_active_prompts(session, customer_id=customer_id, module=module, language='sv')
        assessor = LlmResearchAssessor(
            system_prompt=prompts['research.assessment.system'], user_prompt=prompts['research.assessment.user'],
            provider=settings.llm_provider, model=settings.selected_llm_model,
        )
        return await evaluate_scenarios(assessor, evidence, output, repeats=repeats)
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--customer-id', type=int, required=True)
    parser.add_argument('--module', required=True)
    parser.add_argument('--case-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(evaluate(
        args.customer_id, args.module, args.case_report, args.output, args.repeats,
    )) else 1)
