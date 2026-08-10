import os
import tempfile

# Required before importing app.config — Settings fails without keys.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.session import get_session
from app.llm import set_structured_completer, set_text_completer, set_text_streamer
from app.llm.vision import set_vision_completer
from app.main import create_app
from app.services import jobs as jobs_service
from app.services.population_generate import clear_generations
from app.services.image_cache import clear_image_cache
from app.services.ssr import clear_embedding_cache, set_embedder

# Isolate disk cache from developer machine data/.
_EMBED_CACHE_ROOT = tempfile.mkdtemp(prefix="ssr-embed-cache-")
settings.embedding_cache_dir = _EMBED_CACHE_ROOT
_IMAGE_CACHE_ROOT = tempfile.mkdtemp(prefix="image-cache-")
settings.image_cache_dir = _IMAGE_CACHE_ROOT


@pytest.fixture(autouse=True)
def _reset_llm_completers():
    clear_embedding_cache()
    clear_image_cache()
    yield
    set_structured_completer(None)
    set_text_completer(None)
    set_text_streamer(None)
    set_vision_completer(None)
    set_embedder(None)
    clear_embedding_cache()
    clear_image_cache()


@pytest.fixture
async def client():
    clear_generations()
    settings.persona_generator = "stub"
    settings.deepseek_api_key = "test-key-not-real"
    settings.openai_api_key = "test-openai-key-not-real"
    settings.simulation_engine = "none"

    async def _mock_text(_messages: list[dict[str, str]]) -> str:
        return "Mockad personasvar för tester."

    set_text_completer(_mock_text)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.anchor_store import (
        backfill_configuration_anchor_sets,
        ensure_default_anchor_sets,
    )
    from app.services.prompt_store import ensure_default_configurations

    async with session_factory() as seed_session:
        await ensure_default_anchor_sets(seed_session)
        await ensure_default_configurations(seed_session)
        await backfill_configuration_anchor_sets(seed_session)

    jobs_service.set_job_session_factory(session_factory)
    jobs_service.set_schedule_hook(None)
    jobs_service.reset_simulation_job_semaphore()
    settings.max_concurrent_simulation_jobs = 2

    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    jobs_service.set_job_session_factory(None)
    jobs_service.set_schedule_hook(None)
    await engine.dispose()
