import os
import tempfile
from datetime import UTC, datetime, timedelta

# Required before importing app.config — Settings fails without keys.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-jwt-secret-not-real")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-supabase-service-role-not-real")
os.environ["LOG_DIR"] = ""

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import UserAccount
from app.database.session import get_session
from app.llm import (
    set_structured_completer,
    set_text_completer,
    set_text_streamer,
    set_tools_completer,
)
from app.llm.vision import set_vision_completer
from app.main import create_app
from app.schemas.domain import FollowUpQuestions
from app.services import jobs as jobs_service
from app.services.image_cache import clear_image_cache
from app.services.kund_store import bolag_demo_customer_id, ensure_default_kunder
from app.services.ssr import clear_embedding_cache, set_embedder

# Isolate disk cache / rotating logs from developer machine data/.
_EMBED_CACHE_ROOT = tempfile.mkdtemp(prefix="ssr-embed-cache-")
settings.embedding_cache_dir = _EMBED_CACHE_ROOT
_IMAGE_CACHE_ROOT = tempfile.mkdtemp(prefix="image-cache-")
settings.image_cache_dir = _IMAGE_CACHE_ROOT
_BOLAGSAPI_CACHE_ROOT = tempfile.mkdtemp(prefix="bolagsapi-cache-")
settings.bolagsapi_cache_dir = _BOLAGSAPI_CACHE_ROOT
settings.log_dir = ""

# Seeded by ensure_default_kunder() as Devbrains (primary OS tenant).
TEST_CUSTOMER_ID = 1
# Default projekt under Devbrains from ensure_default_kunder().
TEST_PROJECT_ID = 1

TEST_JWT_SECRET = "test-supabase-jwt-secret-not-real"
ADMIN_USER_ID = "00000000-0000-4000-8000-aaaaaaaaaaaa"
USER_USER_ID = "00000000-0000-4000-8000-bbbbbbbbbbbb"
BOLAG_USER_ID = "00000000-0000-4000-8000-cccccccccccc"


def mint_access_token(
    *,
    sub: str,
    email: str = "test@example.com",
    secret: str = TEST_JWT_SECRET,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _reset_llm_completers():
    clear_embedding_cache()
    clear_image_cache()
    yield
    set_structured_completer(None)
    set_text_completer(None)
    set_text_streamer(None)
    set_tools_completer(None)
    set_vision_completer(None)
    set_embedder(None)
    clear_embedding_cache()
    clear_image_cache()


@pytest.fixture
async def client():
    settings.persona_generator = "stub"
    settings.deepseek_api_key = "test-key-not-real"
    settings.openai_api_key = "test-openai-key-not-real"
    settings.supabase_jwt_secret = TEST_JWT_SECRET
    settings.simulation_engine = "none"

    async def _mock_text(_messages: list[dict[str, str]]) -> str:
        return "Mockad personasvar för tester."

    async def _mock_structured(_messages: list[dict[str, str]], response_model: type):
        if response_model is FollowUpQuestions:
            return FollowUpQuestions(
                questions=[
                    "Hur påverkar det din vardag?",
                    "Vad tänker du om partierna i frågan?",
                    "Har du ändrat åsikt med åren?",
                ]
            )
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_mock_text)
    set_structured_completer(_mock_structured)

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
    from app.services.label_vocabulary import ensure_vocabularies_seeded
    from app.services.dd.default_experts import ensure_default_expert_personas
    from app.services.panel.module_defaults import ensure_module_panel_defaults
    from app.services.prompt_store import ensure_default_configurations

    async with session_factory() as seed_session:
        await ensure_default_kunder(seed_session)
        await ensure_default_anchor_sets(seed_session)
        await ensure_vocabularies_seeded(seed_session)
        await ensure_default_configurations(seed_session)
        await backfill_configuration_anchor_sets(seed_session)
        await ensure_module_panel_defaults(seed_session)
        await ensure_default_expert_personas(seed_session)
        bolag_id = await bolag_demo_customer_id(seed_session)
        seed_session.add(
            UserAccount(
                id=ADMIN_USER_ID,
                email="admin@test.local",
                role="admin",
                kund_id=None,
            )
        )
        seed_session.add(
            UserAccount(
                id=USER_USER_ID,
                email="user@test.local",
                role="user",
                kund_id=TEST_CUSTOMER_ID,
            )
        )
        seed_session.add(
            UserAccount(
                id=BOLAG_USER_ID,
                email="bolag@test.local",
                role="bolag",
                kund_id=bolag_id,
            )
        )
        await seed_session.commit()

    jobs_service.set_job_session_factory(session_factory)
    jobs_service.set_schedule_hook(None)
    jobs_service.reset_simulation_job_semaphore()
    settings.max_concurrent_simulation_jobs = 2

    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    admin_token = mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as ac:
        yield ac

    jobs_service.set_job_session_factory(None)
    jobs_service.set_schedule_hook(None)
    await engine.dispose()


@pytest.fixture
async def client_db(client):
    """HTTP client and its session factory (same in-memory DB)."""
    factory = jobs_service.job_session_factory()
    assert factory is not None
    yield client, factory


@pytest.fixture
def admin_token() -> str:
    return mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")


@pytest.fixture
def user_token() -> str:
    return mint_access_token(sub=USER_USER_ID, email="user@test.local")


@pytest.fixture
def bolag_token() -> str:
    return mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")


@pytest.fixture
async def user_client(client):
    """Same app/DB as client, but Authorization is the Devbrains user role."""
    token = mint_access_token(sub=USER_USER_ID, email="user@test.local")
    client.headers["Authorization"] = f"Bearer {token}"
    yield client


@pytest.fixture
async def bolag_client(client):
    """Same app/DB as client, but Authorization is the bolag-demo role."""
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
