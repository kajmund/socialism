import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api import (
    catalog,
    configurations,
    embeddings,
    execution,
    expert_memory,
    feedback,
    health,
    help,
    jobs,
    kunder,
    llm_settings,
    local_login,
    me,
    modules,
    panel,
    panel_catalog,
    personas,
    populations,
    reports,
    spindoctor,
    underlag,
    users,
    ws,
)
from app.config import settings
from app.logging import configure_logging
from app.modules.registry import MODULE_REGISTRY
from app.services import jobs as jobs_service
from app.services.knowledge.supabase_vector_client import start_supabase_vector_runtime
from app.services.knowledge.vector_store import SupabaseVectorBucketStore
from app.services.kund_store import ensure_default_kunder
from app.services.llm_runtime_settings import load_runtime_settings
from app.services.panel.module_defaults import ensure_module_panel_defaults
from app.services.prompt_store import ensure_default_configurations
from app.services.research.composition import set_knowledge_vector_store_factory
from app.services.research_worker import (
    start_research_reclaim_loop,
    stop_research_reclaim_loop,
)

logger = logging.getLogger(__name__)


def _require_chat_llm() -> None:
    if settings.selected_llm_api_key:
        return
    raise RuntimeError(
        f"{settings.chat_llm_key_env_name} is required when "
        f"LLM_PROVIDER={settings.llm_provider}"
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _require_chat_llm()
    if not settings.openai_api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required (embeddings / SSR)")
    if not settings.supabase_jwt_secret.strip():
        raise RuntimeError("SUPABASE_JWT_SECRET is required")
    if not settings.supabase_url.strip():
        raise RuntimeError("SUPABASE_URL is required")
    if not settings.supabase_service_role_key.strip():
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required")
    settings.apply_oasis_env()
    factory = jobs_service.job_session_factory()
    try:
        async with factory() as session:
            await jobs_service.fail_interrupted_jobs(session)
    except (OperationalError, ProgrammingError) as exc:
        # Fresh checkout / migration not applied yet — don't block boot.
        logger.warning("Skipping interrupted-job sweep on startup: %s", exc)
    try:
        async with factory() as session:
            await ensure_default_kunder(session)
            await ensure_default_configurations(session)
            await ensure_module_panel_defaults(session)
            await session.commit()
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Skipping configuration prompt backfill on startup: %s", exc)
    try:
        async with factory() as session:
            await load_runtime_settings(session)
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Skipping LLM runtime settings load on startup: %s", exc)
    vector_runtime = None
    _app.state.research_vector = {"status": "disabled"}
    reclaim_stop = None
    if settings.research_worker_loop_enabled:
        vector_runtime = await start_supabase_vector_runtime(settings)
        vector_store = SupabaseVectorBucketStore(vector_runtime.client)
        set_knowledge_vector_store_factory(lambda: vector_store)
        _app.state.research_vector = {
            "status": vector_runtime.health.status,
            "bucket": vector_runtime.health.bucket,
            "index": vector_runtime.health.index,
            "dimension": vector_runtime.health.dimension,
        }
        reclaim_stop = start_research_reclaim_loop()
    try:
        yield
    finally:
        if reclaim_stop is not None:
            await stop_research_reclaim_loop(reclaim_stop)
        set_knowledge_vector_store_factory(None)
        if vector_runtime is not None:
            await vector_runtime.close()


def create_app() -> FastAPI:
    log_path = configure_logging()
    if log_path is not None:
        logger.info("File logging %s", log_path)
    _require_chat_llm()
    if not settings.openai_api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required (embeddings / SSR)")
    if not settings.supabase_jwt_secret.strip():
        raise RuntimeError("SUPABASE_JWT_SECRET is required")
    if not settings.supabase_url.strip():
        raise RuntimeError("SUPABASE_URL is required")
    if not settings.supabase_service_role_key.strip():
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required")
    app = FastAPI(title="Opinionssimulator", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(local_login.router)
    app.include_router(me.router)
    app.include_router(configurations.router)
    app.include_router(kunder.router)
    app.include_router(users.router)
    app.include_router(modules.router)
    app.include_router(catalog.router)
    app.include_router(personas.router)
    app.include_router(populations.router)
    for module in MODULE_REGISTRY.values():
        app.include_router(module.router)
    app.include_router(panel.router)
    app.include_router(panel_catalog.router)
    app.include_router(execution.router)
    app.include_router(jobs.router)
    app.include_router(reports.router)
    app.include_router(embeddings.router)
    app.include_router(expert_memory.router)
    app.include_router(llm_settings.router)
    app.include_router(llm_settings.capabilities_router)
    app.include_router(feedback.router)
    app.include_router(help.router)
    app.include_router(spindoctor.router)
    app.include_router(underlag.router)
    app.include_router(ws.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
