"""A fresh application database must receive the coverage-preserving planner prompt."""

import pytest

from app.services.prompt_fields_store import get_prompt_field_by_key

pytestmark = pytest.mark.research_reuse


@pytest.mark.parametrize(
    ("attribute", "requirements"),
    [
        (
            "default_sv",
            [
                "alla uttryckligen saknade dimensioner",
                "Sammanslagning får inte tappa någon dimension",
                "måste efterfrågas i själva frågan",
            ],
        ),
        (
            "default_en",
            [
                "all explicitly missing dimensions",
                "Consolidation must not drop any dimension",
                "request it in the question itself",
            ],
        ),
        (
            "default_nb",
            [
                "alla uttryckligen saknade dimensioner",
                "Sammanslagning får inte tappa någon dimension",
                "måste efterfrågas i själva frågan",
            ],
        ),
    ],
)
async def test_empty_database_startup_seeds_gap_coverage_in_planner(
    client_db, attribute, requirements
):
    _client, factory = client_db
    async with factory() as session:
        row = await get_prompt_field_by_key(session, "research.followup.system")
        assert row is not None and row.active
        assert {"dd", "politik", "expertgranskning"} <= set(row.modules)
        for requirement in requirements:
            assert requirement in getattr(row, attribute)
        for key in ("research.followup.coverage.system", "research.followup.coverage.user"):
            evaluator = await get_prompt_field_by_key(session, key)
            assert evaluator is not None and evaluator.active
            assert getattr(evaluator, attribute).strip()
