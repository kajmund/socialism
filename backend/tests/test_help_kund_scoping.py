"""Help chat must not leak another tenant's data via customer_id or view params."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona
from app.schemas.domain import HelpViewContext
from app.services.help_read_context import build_help_context
from app.services.prompt_store import ensure_default_configurations


@pytest.mark.asyncio
async def test_help_context_denies_other_kund_persona() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        await ensure_default_configurations(session)
        session.add(
            Persona(
                id="bolag-secret-persona",
                customer_id=2,
                name="Bolag hemlig",
                age=40,
                occ="VD",
                district="Göteborg",
                quote="SECRET_BOLAG_QUOTE_XYZ",
                origin="manuell",
            )
        )
        await session.commit()

        view = HelpViewContext(
            path="/personas/bolag-secret-persona",
            view_key="personas.detail",
            label="Persona",
            params={"id": "bolag-secret-persona"},
            search={},
        )
        text = await build_help_context(
            session,
            view=view,
            query="visa persona",
            customer_id=1,
        )
        assert "SECRET_BOLAG_QUOTE_XYZ" not in text
        assert "Not available for this tenant" in text

    await engine.dispose()
