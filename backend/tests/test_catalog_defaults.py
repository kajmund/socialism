import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import CatalogList, Configuration
from app.serializers import utcnow
from app.services.catalog_defaults import CATALOG_DEFAULTS
from app.services.catalog_items import catalog_items_as_json, coerce_catalog_items
from app.services.catalog_store import ensure_catalog_defaults
from app.services.kund_store import ensure_default_kunder


def _labels_for(key: str) -> list[str]:
    row = next(item for item in CATALOG_DEFAULTS if item["key"] == key)
    return [item["label"] for item in row["items"]]


def test_default_ton_is_not_majority_negative():
    labels = _labels_for("ton")
    assert "Saklig och nyanserad" in labels
    assert "Optimistisk och pratglad" in labels
    negative = {
        "Sarkastisk och otålig",
        "Cynisk mot politiker",
        "Uppgiven men engagerad",
    }
    assert sum(1 for label in labels if label in negative) < len(labels) / 2


def test_default_fortroende_includes_high_trust():
    labels = _labels_for("fortroende")
    assert "Högt för kommunen" in labels
    assert "Blandat" in labels
    assert "Blandat, skeptisk generellt" not in labels


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _add_config_with_ton(session: AsyncSession, labels: list[str]) -> int:
    await ensure_default_kunder(session)
    config = Configuration(name="Test", language="sv", prompts={}, customer_id=1)
    session.add(config)
    await session.flush()
    session.add(
        CatalogList(
            configuration_id=config.id,
            key="ton",
            section="rost_media",
            title="Ton",
            items=catalog_items_as_json(coerce_catalog_items(labels)),
            updated_at=utcnow(),
        )
    )
    await session.commit()
    return config.id


async def _ton_labels(session: AsyncSession, configuration_id: int) -> list[str]:
    row = (
        await session.execute(
            select(CatalogList).where(
                CatalogList.configuration_id == configuration_id,
                CatalogList.key == "ton",
            )
        )
    ).scalar_one()
    return [item.label for item in coerce_catalog_items(row.items)]


@pytest.mark.asyncio
async def test_ensure_replaces_unmodified_stock_ton(session: AsyncSession):
    config_id = await _add_config_with_ton(
        session,
        [
            "Sarkastisk och otålig",
            "Uppgiven men engagerad",
            "Optimistisk och pratglad",
            "Direkt och kort i tonen",
            "Cynisk mot politiker",
        ],
    )
    await ensure_catalog_defaults(session, config_id)
    assert await _ton_labels(session, config_id) == _labels_for("ton")


@pytest.mark.asyncio
async def test_ensure_keeps_edited_ton_list(session: AsyncSession):
    config_id = await _add_config_with_ton(
        session, ["Varm men bestämd", "Egen röst"]
    )
    await ensure_catalog_defaults(session, config_id)
    assert await _ton_labels(session, config_id) == ["Varm men bestämd", "Egen röst"]
