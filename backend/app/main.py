import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api import (
    catalog,
    configurations,
    embeddings,
    feedback,
    health,
    help,
    jobs,
    kunder,
    modules,
    panel,
    panel_catalog,
    personas,
    populations,
    reports,
    spindoctor,
    users,
    ws,
)
from app.config import settings
from app.logging import configure_logging
from app.modules.registry import MODULE_REGISTRY
from app.services import jobs as jobs_service
from app.services.kund_store import ensure_default_kunder
from app.services.panel.module_defaults import ensure_module_panel_defaults
from app.services.prompt_store import ensure_default_configurations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.deepseek_api_key.strip():
        raise RuntimeError("DEEPSEEK_API_KEY is required")
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
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Skipping configuration prompt backfill on startup: %s", exc)
    yield


def create_app() -> FastAPI:
    log_path = configure_logging()
    if log_path is not None:
        logger.info("File logging %s", log_path)
    if not settings.deepseek_api_key.strip():
        raise RuntimeError("DEEPSEEK_API_KEY is required")
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
    app.include_router(jobs.router)
    app.include_router(reports.router)
    app.include_router(embeddings.router)
    app.include_router(feedback.router)
    app.include_router(help.router)
    app.include_router(spindoctor.router)
    app.include_router(ws.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
