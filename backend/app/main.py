import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api import (
    catalog,
    clause_ssr,
    configurations,
    embeddings,
    execution,
    expert_memory,
    feedback,
    health,
    help,
    jobs,
    kunder,
    live_speech,
    llm_settings,
    local_login,
    me,
    modules,
    overgraph,
    panel,
    panel_catalog,
    personas,
    populations,
    reports,
    sme,
    sme_group_voice_ws,
    sme_ws,
    spindoctor,
    tts_cache,
    underlag,
    workspace_chats,
    users,
    voice_workspaces,
    document_ingest_batches,
    document_properties,
    voice_workspace_inbox,
    workspace_exports,
    workspace_conversations,
    workspaces,
    ws,
)
from app.config import EMBEDDING_MODEL_DIMENSIONS, settings
from app.database.session import engine
from app.logging import configure_logging
from app.modules.registry import MODULE_REGISTRY
from app.services import jobs as jobs_service
from app.services import retrieval_index
from app.services.expertgranskning.memory import close_default_expert_memory
from app.services.graph_v2.worker import start_graph_ingest_loop, stop_graph_ingest_loop
from app.services.overgraph.catalogs import (
    OverGraphRuntime,
    OwnerReadRequiredError,
    catalog_root,
    open_runtime,
    set_owner_mode,
    set_runtime,
)
from app.services.overgraph.owner_guards import set_direct_writes_forbidden
from app.services.overgraph.owner_registry import (
    close_owner_registry,
    connect_owner_registry,
    parse_memory_owner_route,
    parse_tenant_owner_sockets,
)
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.knowledge.supabase_vector_client import start_supabase_vector_runtime
from app.services.knowledge.vector_store import SupabaseVectorBucketStore
from app.services.kund_store import ensure_default_kunder
from app.services.live_speech_sessions import LiveSpeechRegistry
from app.services.llm_runtime_settings import load_runtime_settings
from app.services.panel.module_defaults import ensure_module_panel_defaults
from app.services.prompt_store import ensure_default_configurations
from app.llm.lagen_nu_selector import LlmLagenNuSelector
from app.services.research.composition import (
    set_knowledge_vector_store_factory,
    set_lagen_nu_selector_factory,
)
from app.services.research_worker import (
    start_research_reclaim_loop,
    stop_research_reclaim_loop,
)

logger = logging.getLogger(__name__)


def _require_chat_llm() -> None:
    if settings.selected_llm_api_key:
        return
    raise RuntimeError(
        f"{settings.chat_llm_key_env_name} is required when LLM_PROVIDER={settings.llm_provider}"
    )


async def _open_retrieval_index() -> None:
    """Open/build/reconcile the derived lexical index without blocking the loop."""
    await asyncio.to_thread(retrieval_index.ensure_current)


async def _prepare_graph_access(owner_mode: bool, app: FastAPI) -> None:
    set_owner_mode(owner_mode)
    set_direct_writes_forbidden(owner_mode)
    set_runtime(_graph_runtime_for_mode(owner_mode))
    if owner_mode:
        logger.warning(
            "owner read mode: knowledge catalog opened only by the owner; "
            "retrieval index and graph writeback loops are disabled",
        )
        app.state.retrieval_index = {"status": "owner_mode_pending"}
        return
    await _open_retrieval_index()


def _start_graph_worker(owner_mode: bool, factory):
    if not settings.graph_ingest_loop_enabled:
        return None
    return start_graph_ingest_loop(factory)


def _graph_runtime_for_mode(owner_mode: bool) -> OverGraphRuntime:
    """Owner mode keeps the knowledge catalog out of the backend process."""
    root = catalog_root(settings.overgraph_dir)
    memory_dimension = EMBEDDING_MODEL_DIMENSIONS[settings.mem0_embedding_model]
    if owner_mode:
        from app.services.overgraph.catalogs import open_catalog

        return OverGraphRuntime(
            None,
            open_catalog(root / "memory", kind="memory", dimension=memory_dimension),
        )
    return open_runtime(
        root,
        knowledge_dimension=settings.embedding_dimension,
        memory_dimension=memory_dimension,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: PLR0915
    _require_chat_llm()
    if not settings.openai_api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required (embeddings / SSR)")
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
    owner_runtime = get_owner_runtime()
    await owner_runtime.connect(
        settings.overgraph_owner_socket,
        catalog_id=settings.overgraph_owner_catalog_id or None,
    )
    _app.state.overgraph_owner = owner_runtime.status
    tenant_routes = parse_tenant_owner_sockets(settings.overgraph_tenant_owner_sockets)
    owner_routes = tenant_routes + parse_memory_owner_route(settings.overgraph_memory_owner_socket)
    _app.state.overgraph_tenant_owners = (
        await connect_owner_registry(owner_routes) if owner_routes else {}
    )
    owner_mode = owner_runtime.client is not None
    if owner_mode and not tenant_routes:
        raise RuntimeError(
            "owner mode requires OVERGRAPH_TENANT_OWNER_SOCKETS for tenant catalogs"
        )
    await _prepare_graph_access(owner_mode, _app)
    _app.state.research_vector = {"status": "disabled"}
    reclaim_stop = None
    set_lagen_nu_selector_factory(LlmLagenNuSelector)
    _app.state.live_speech_registry = LiveSpeechRegistry()
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
    graph_task = _start_graph_worker(owner_mode, factory)
    try:
        yield
    finally:
        await _app.state.live_speech_registry.close_all()
        if reclaim_stop is not None:
            await stop_research_reclaim_loop(reclaim_stop)
        await stop_graph_ingest_loop(graph_task)
        set_knowledge_vector_store_factory(None)
        set_lagen_nu_selector_factory(None)
        if vector_runtime is not None:
            await vector_runtime.close()
        try:
            await close_owner_registry()
            await owner_runtime.close()
            close_default_expert_memory()
        finally:
            set_runtime(None)
            await engine.dispose()


def _register_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(local_login.router)
    from app.api import profiles
    app.include_router(profiles.router)
    app.include_router(me.router)
    app.include_router(configurations.router)
    app.include_router(kunder.router)
    app.include_router(users.router)
    app.include_router(workspaces.router)
    app.include_router(workspace_chats.router)
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
    app.include_router(sme.router)
    app.include_router(sme_ws.router)
    app.include_router(sme_group_voice_ws.router)
    app.include_router(live_speech.router)
    app.include_router(voice_workspaces.router)
    app.include_router(document_ingest_batches.router)
    app.include_router(document_properties.router)
    app.include_router(clause_ssr.router)
    app.include_router(voice_workspace_inbox.router)
    app.include_router(workspace_exports.router)
    app.include_router(workspace_conversations.router)
    app.include_router(embeddings.router)
    app.include_router(tts_cache.router)
    app.include_router(overgraph.router)
    app.include_router(expert_memory.router)
    app.include_router(llm_settings.router)
    app.include_router(llm_settings.capabilities_router)
    app.include_router(feedback.router)
    app.include_router(help.router)
    app.include_router(spindoctor.router)
    app.include_router(underlag.router)
    app.include_router(ws.router)


def create_app() -> FastAPI:
    log_path = configure_logging()
    if log_path is not None:
        logger.info("File logging %s", log_path)
    _require_chat_llm()
    if not settings.openai_api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required (embeddings / SSR)")
    if not settings.supabase_url.strip():
        raise RuntimeError("SUPABASE_URL is required")
    if not settings.supabase_service_role_key.strip():
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required")
    app = FastAPI(title="Opinionssimulator", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(OwnerReadRequiredError)
    async def _owner_read_required(_request, exc: OwnerReadRequiredError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={"detail": "knowledge_requires_owner_read", "message": str(exc)},
        )

    app.state.live_speech_registry = LiveSpeechRegistry()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Workspace-Source-Version", "X-Workspace-File-Sha256"],
    )
    _register_routers(app)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
