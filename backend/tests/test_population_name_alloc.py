"""Unique population name allocation when generating."""

import pytest

from app.database.models import Population
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.kund_store import default_os_customer_id
from app.services.population_persist import allocate_unique_population_name


@pytest.mark.asyncio
async def test_allocate_unique_population_name_suffixes(client):
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        customer_id = await default_os_customer_id(session)
        for name in ("Demo", "Demo (2)"):
            session.add(
                Population(
                    customer_id=customer_id,
                    name=name,
                    size=0,
                    versions=1,
                    fingerprint=[[33, 34, 33], [33, 34, 33], [33, 34, 33]],
                    recipe={},
                    updated_at=utcnow(),
                )
            )
        await session.commit()

        assert (
            await allocate_unique_population_name(
                session, "Demo", customer_id=customer_id
            )
            == "Demo (3)"
        )
        assert (
            await allocate_unique_population_name(
                session, "  ", customer_id=customer_id
            )
            == "Namnlös population"
        )
        assert (
            await allocate_unique_population_name(
                session, "Fresh", customer_id=customer_id
            )
            == "Fresh"
        )
