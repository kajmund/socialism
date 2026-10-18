"""Ephemeral database and production OverGraph fixture for the benchmark."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, Kund, StoredObject, UserAccount
from app.database.sqlite import async_engine_kwargs
from app.database.workspace_models import VoiceWorkspace
from app.database.workspaces import Workspace, WorkspaceChat, WorkspaceMembership
from app.schemas.workspace import WorkspaceState
from app.services.document_find.fixture import add_document
from app.services.document_find.taxonomy import TYPE_LABELS_SV
from app.services.document_qa.tenants import TenantCatalogs, set_tenant_catalogs
from app.services.workspace.tool_handlers import ToolContext, find_documents
from scripts.document_presentation_benchmark.cases import (
    DOCUMENT_TYPES,
    fixture_inventory,
    source_id,
)
from scripts.document_presentation_benchmark.types import (
    BenchmarkEnvironment,
    FindRunner,
)

CUSTOMER_ID = 1
USER_ID = "benchmark-user"
WORKSPACE_ID = "benchmark-canvas"
CONTAINER_ID = "benchmark-workspace"
CHAT_ID = "benchmark-chat"


def production_runner(environment: BenchmarkEnvironment) -> FindRunner:
    async def run(arguments: dict[str, Any], state: WorkspaceState) -> dict[str, Any]:
        async with environment.sessions() as session:
            context = ToolContext(
                session=session,
                workspace=environment.workspace,
                user=environment.user,
                operation=SimpleNamespace(external_started=False),
                state=state,
                language="sv",
            )
            return await find_documents(context, arguments)

    return run


async def create_environment(
    root: Path,
) -> tuple[BenchmarkEnvironment, Any]:
    database_url = f"sqlite+aiosqlite:///{root / 'benchmark.db'}"
    engine = create_async_engine(database_url, **async_engine_kwargs(database_url))
    async with engine.begin() as connection:
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    registry = TenantCatalogs(
        root / "overgraph",
        dimension=settings.embedding_dimension,
    )
    set_tenant_catalogs(registry)
    user = UserAccount(
        id=USER_ID,
        email="benchmark@example.invalid",
        role="admin",
        kund_id=CUSTOMER_ID,
    )
    workspace = VoiceWorkspace(
        id=WORKSPACE_ID,
        workspace_id=CONTAINER_ID,
        chat_id=CHAT_ID,
        customer_id=CUSTOMER_ID,
        owner_user_id=USER_ID,
        creation_key="benchmark",
        creation_payload_hash="0" * 64,
        title="Benchmark",
        module="dd",
        state={},
    )
    async with sessions() as session:
        await _seed_database(session, user, workspace)
        await _seed_documents(session, registry)
        await session.commit()
    return (
        BenchmarkEnvironment(
            sessions=sessions,
            registry=registry,
            user=user,
            workspace=workspace,
            inventory=frozenset(
                source
                for source_ids in fixture_inventory().values()
                for source in source_ids
            ),
        ),
        engine,
    )


async def _seed_database(
    session: AsyncSession,
    user: UserAccount,
    canvas: VoiceWorkspace,
) -> None:
    session.add(Kund(id=CUSTOMER_ID, name="Benchmark", slug="benchmark", available_modules=[]))
    await session.flush()
    session.add(user)
    await session.flush()
    session.add(
        Workspace(
            id=CONTAINER_ID,
            customer_id=CUSTOMER_ID,
            name="Benchmark",
            kind="company",
            created_by_user_id=USER_ID,
        )
    )
    await session.flush()
    session.add(
        WorkspaceMembership(
            workspace_id=CONTAINER_ID,
            user_id=USER_ID,
            role="manager",
        )
    )
    session.add(
        WorkspaceChat(
            id=CHAT_ID,
            customer_id=CUSTOMER_ID,
            workspace_id=CONTAINER_ID,
            owner_user_id=USER_ID,
            module="dd",
            title="Benchmark",
        )
    )
    await session.flush()
    session.add(canvas)
    await session.flush()


async def _seed_documents(
    session: AsyncSession,
    registry: TenantCatalogs,
) -> None:
    catalog = registry.open_for(CUSTOMER_ID)
    for document_type in DOCUMENT_TYPES:
        label = TYPE_LABELS_SV[document_type]
        for ordinal in range(4):
            document_id = f"{document_type}-{ordinal}"
            object_id = source_id(document_type, ordinal)
            await add_document(
                catalog,
                document_id=document_id,
                title=f"{label} {ordinal + 1}",
                opening=f"{label}.",
                passages=[
                    (
                        f"{label} för benchmark.",
                        tuple(0.1 for _ in range(settings.embedding_dimension)),
                    )
                ],
                customer_id=CUSTOMER_ID,
            )
            session.add(
                StoredObject(
                    id=object_id,
                    customer_id=CUSTOMER_ID,
                    workspace_id=CONTAINER_ID,
                    module="dd",
                    kind="document",
                    bucket="benchmark",
                    object_key=object_id,
                    filename=f"{document_id}.pdf",
                    content_type="application/pdf",
                    size_bytes=1,
                )
            )
            session.add(
                CanonicalDocumentRecord(
                    id=document_id,
                    scope_type="customer",
                    scope_key=f"customer:{CUSTOMER_ID}",
                    customer_id=CUSTOMER_ID,
                    source_object_id=object_id,
                    source_type="upload",
                    canonical_uri=f"benchmark://{document_id}",
                    title=f"{label} {ordinal + 1}",
                    extra={},
                )
            )
