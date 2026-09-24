"""The assessment benchmark must detect weak verdicts and invalid inputs."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchAssessmentError,
    ResearchNeedAssessment,
)
from scripts.evaluate_research_assessment_scope import (
    CASES,
    QUESTION,
    SCENARIOS,
    check_assessment,
    evaluate_scenarios,
    load_evidence,
)


def expected_draft(scenario):
    return ResearchAssessmentDraft(
        result='sufficient' if scenario.sufficient else 'insufficient', rationale='fixture',
        need_assessments=[ResearchNeedAssessment(
            research_need_id='n1', sufficient=scenario.sufficient,
            supporting_evidence_ids=['1999s408'] if '1999s408' in scenario.case_ids else [],
            missing_or_weak='' if scenario.sufficient else 'Missing required evidence',
            further_information=None if scenario.sufficient else 'Retrieve the missing evidence',
        )],
    )


@pytest.mark.parametrize('scenario', SCENARIOS, ids=lambda row: row.name)
def test_oracle_rejects_wrong_verdict_and_wrong_support(scenario):
    draft = expected_draft(scenario)
    assert all(check_assessment(scenario, draft).values())
    wrong = replace(draft, result='insufficient' if scenario.sufficient else 'sufficient')
    assert not check_assessment(scenario, wrong)['overall_verdict']
    wrong = replace(draft, need_assessments=[replace(
        draft.need_assessments[0], supporting_evidence_ids=['2010s467'],
    )])
    assert not check_assessment(scenario, wrong)['support']


def test_sufficient_with_unresolved_gap_fails():
    scenario = SCENARIOS[0]
    draft = replace(expected_draft(scenario), gaps=['Unresolved requirement'])
    assert not check_assessment(scenario, draft)['gap_consistency']


async def test_error_does_not_skip_controls_and_partial_report_is_not_a_pass(tmp_path):
    output = tmp_path / 'assessment.json'
    calls = []

    class Assessor:
        async def assess(self, plan, evidence):
            if calls:
                assert json.loads(output.read_text())['complete'] is False
            scenario = SCENARIOS[len(calls)]
            calls.append(plan)
            if len(calls) == 1:
                raise ResearchAssessmentError('typed failure')
            return expected_draft(scenario)

    evidence = {key: SimpleNamespace(content_hash=key) for key in CASES}
    assert not await evaluate_scenarios(Assessor(), evidence, output, repeats=1)
    report = json.loads(output.read_text())
    assert len(calls) == len(SCENARIOS)
    assert report['complete'] is True
    assert report['passed'] is False
    assert report['results'][0]['failure'] == 'typed failure'
    assert all(row['passed'] for row in report['results'][1:])


@pytest.mark.parametrize('mutation', ['failed', 'wrong_question', 'duplicate', 'changed', 'truncated'])
async def test_untrusted_case_report_cannot_supply_arbitrary_sources(mutation):
    rows = [{'source': 'https://lagen.nu/dom/nja/' + key, 'sha256': 'original'} for key in CASES]
    report = {'question': QUESTION, 'passed': True, 'cases': rows}
    if mutation == 'failed':
        report['passed'] = False
    elif mutation == 'wrong_question':
        report['question'] = 'different question'
    elif mutation == 'duplicate':
        rows[1] = rows[0]

    class Client:
        async def get_document(self, uri, **kwargs):
            assert mutation in {'changed', 'truncated'}
            return SimpleNamespace(text='changed source', truncated=mutation == 'truncated')

    with pytest.raises(ValueError):
        await load_evidence(report, Client())
