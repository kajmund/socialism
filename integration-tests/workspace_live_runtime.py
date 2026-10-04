"""Isolated PostgreSQL schema with real configured storage, vectors and LLMs.

No production schema or application data is modified. Cleanup uses the exact
remote keys captured before each write, including failed writes.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


class Observation:
    def __init__(self, report: dict, path: Path):
        self.report, self.path = report, path
        self.checked_out = 0
        self.connection_owners = {}
        self.storage_keys, self.vector_keys = set(), set()
        self.restore = []

    def save(self):
        self.report["remote_inventory"] = {
            "storage": sorted([list(value) for value in self.storage_keys]),
            "vectors": sorted(self.vector_keys),
        }
        self.path.write_text(json.dumps(self.report, ensure_ascii=False, indent=2))

    def assertion(self, code, passed, **details):
        self.report["assertions"].append({"code": code, "passed": bool(passed), **details})
        self.save()

    def watch_engine(self, engine):
        from sqlalchemy import event

        def checkout(_connection, record, _proxy):
            self.checked_out += 1
            self.connection_owners[id(record)] = id(asyncio.current_task())

        def checkin(_connection, record):
            self.checked_out -= 1
            self.connection_owners.pop(id(record), None)

        event.listen(engine.sync_engine, "checkout", checkout)
        event.listen(engine.sync_engine, "checkin", checkin)

    def wrap(self, owner, attribute, label, capture=None):
        original = getattr(owner, attribute)

        async def observed(*args, **kwargs):
            own_count = sum(
                owner == id(asyncio.current_task()) for owner in self.connection_owners.values()
            )
            row = {
                "boundary": label,
                "checked_out_at_start": own_count,
                "pool_checked_out": self.checked_out,
            }
            self.report["external_calls"].append(row)
            if capture:
                capture(args, kwargs)
            self.save()
            try:
                result = await original(*args, **kwargs)
                row["status"] = "returned"
                return result
            except BaseException as exc:
                row.update(status="error", error_type=type(exc).__name__)
                raise
            finally:
                self.save()

        self.restore.append((owner, attribute, original))
        setattr(owner, attribute, observed)

    def install(self):
        from openai.resources.chat.completions import AsyncCompletions
        from openai.resources.embeddings import AsyncEmbeddings
        from app.services import document_upload, stored_objects
        from app.services.knowledge import supabase_provider
        from app.services.knowledge.supabase_vector_client import (
            SupabaseStorageVectorClient,
            _record_key,
        )

        def storage_write(args, _kwargs):
            self.storage_keys.add((args[0], args[1]))

        def vector_write(args, kwargs):
            records = kwargs.get("records", args[-1])
            self.vector_keys.update(_record_key(record) for record in records)

        self.wrap(AsyncCompletions, "create", "llm.chat")
        self.wrap(AsyncEmbeddings, "create", "openai.embeddings")
        for owner in (document_upload, stored_objects):
            for attribute in ("ensure_bucket", "put_object", "get_object", "delete_object"):
                if hasattr(owner, attribute):
                    self.wrap(
                        owner,
                        attribute,
                        f"storage.{attribute}",
                        storage_write if attribute == "put_object" else None,
                    )
        self.wrap(supabase_provider, "get_object", "storage.provider.get_object")
        for attribute in ("upsert", "replace", "query", "get", "delete"):
            self.wrap(
                SupabaseStorageVectorClient,
                attribute,
                f"vectors.{attribute}",
                vector_write if attribute in {"upsert", "replace"} else None,
            )

    def close(self):
        for owner, attribute, original in reversed(self.restore):
            setattr(owner, attribute, original)


class LiveRuntime:
    def __init__(self, report_path: Path):
        self.report = {"assertions": [], "external_calls": [], "status": "preparing"}
        self.observation = Observation(self.report, report_path)
        self.schema = f"workspace_live_{uuid4().hex[:12]}"
        self.report["schema"] = self.schema
        self.vector_runtime = None
        self.admin_engine = self.engine = None

    async def _configure_database_environment(self):
        from dotenv import load_dotenv
        from sqlalchemy import text
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import create_async_engine

        load_dotenv(
            os.environ.get("WORKSPACE_LIVE_ENV_FILE", str(REPO / "backend/.env")), override=False
        )
        original_url = os.environ["DATABASE_URL"]
        self.admin_engine = create_async_engine(
            make_url(os.environ["MIGRATION_DATABASE_URL"]).set(drivername="postgresql+psycopg")
        )
        probe_engine = create_async_engine(original_url)
        async with probe_engine.connect() as probe:
            app_role = await probe.scalar(text("SELECT current_user"))
        await probe_engine.dispose()
        async with self.admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        isolated_url = make_url(original_url).update_query_dict(
            {"options": f"-csearch_path={self.schema}"}
        )
        os.environ["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
        os.environ["LOCAL_AUTH_JWT_SECRET"] = secrets.token_urlsafe(48)
        os.environ["RESEARCH_WORKER_LOOP_ENABLED"] = "false"
        os.environ["ALLOW_LOCAL_LOGIN"] = "true"
        os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:5177,http://localhost:5177"
        return app_role

    async def start(self):
        from sqlalchemy import event
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from workspace_pg_setup import initialize_isolated_schema

        app_role = await self._configure_database_environment()
        from app.config import settings
        from app.database.base import Base
        from app.database.session import engine, get_session
        from app.main import create_app
        from app.services import jobs
        from app.services.knowledge.supabase_vector_client import start_supabase_vector_runtime
        from app.services.knowledge.vector_store import SupabaseVectorBucketStore
        from app.services.research.composition import set_knowledge_vector_store_factory

        self.engine = engine

        @event.listens_for(engine.sync_engine, "begin")
        def isolate_transaction(connection):
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{self.schema}"')

        self.factory = async_sessionmaker(engine, expire_on_commit=False)
        self.observation.watch_engine(engine)
        self.report.update(
            await initialize_isolated_schema(
                self.admin_engine,
                schema=self.schema,
                app_role=app_role,
                metadata=Base.metadata,
            )
        )
        await self._seed_customer()
        jobs.set_job_session_factory(self.factory)
        jobs.set_schedule_hook(lambda _job_id: None)
        self.vector_runtime = await start_supabase_vector_runtime(settings)
        self.store = SupabaseVectorBucketStore(self.vector_runtime.client)
        set_knowledge_vector_store_factory(lambda: self.store)
        self.observation.install()
        self.app = create_app()

        async def isolated_session():
            async with self.factory() as session:
                yield session

        self.app.dependency_overrides[get_session] = isolated_session
        self.report["status"] = "ready"
        self.observation.save()

    async def _seed_customer(self):
        from sqlalchemy import text
        from app.database.models import Kund, UserAccount
        from app.services.prompt_store import ensure_default_configurations

        async with self.factory() as session:
            actual_schema = await session.scalar(text("SELECT current_schema()"))
            if actual_schema != self.schema:
                raise RuntimeError("Integration schema isolation failed")
            await ensure_default_configurations(session)
            self.customer_id = secrets.randbelow(900_000_000) + 100_000_000
            self.user_id = f"live-{uuid4().hex}"
            self.email = "erik@fremred.se"
            session.add(
                Kund(
                    id=self.customer_id,
                    name="Integration: juristbyrån",
                    slug=self.schema.replace("_", "-"),
                    product="sme",
                    available_modules=["dd", "expertgranskning"],
                )
            )
            session.add(
                UserAccount(
                    id=self.user_id, email=self.email, role="user", kund_id=self.customer_id
                )
            )
            await session.commit()

    def token(self):
        from app.auth.tokens import mint_access_token

        return mint_access_token(user_id=self.user_id, email=self.email)

    async def _cleanup_vectors(self):
        from httpx import HTTPError
        from storage3.exceptions import StorageException
        from app.services.knowledge.provider import KnowledgeVectorStoreError

        failures = []
        if self.vector_runtime is not None:
            index = self.vector_runtime.client._index
            keys = sorted(self.observation.vector_keys)
            try:
                for offset in range(0, len(keys), 100):
                    await index.delete(keys[offset : offset + 100])
                remaining = []
                for offset in range(0, len(keys), 100):
                    response = await index.get(
                        *keys[offset : offset + 100], return_data=False, return_metadata=True
                    )
                    remaining.extend(response.vectors)
                self.observation.assertion(
                    "exact_vector_inventory_removed", not remaining, keys=len(keys)
                )
            except (HTTPError, StorageException, KnowledgeVectorStoreError) as exc:
                failures.append({"resource": "vectors", "error_type": type(exc).__name__})
        return failures

    async def _cleanup_storage(self):
        from app.services.object_storage import S3ObjectStorage, delete_object, ObjectStorageError
        from botocore.exceptions import BotoCoreError, ClientError
        from httpx import HTTPError

        failures = []
        for bucket, key in self.observation.storage_keys:
            try:
                await delete_object(bucket, key)
                try:
                    await asyncio.to_thread(
                        S3ObjectStorage()._client().head_object, Bucket=bucket, Key=key
                    )
                except ClientError as exc:
                    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    self.observation.assertion(
                        "exact_storage_key_removed", status == 404, bucket=bucket, key=key
                    )
                else:
                    failures.append({"resource": "storage", "bucket": bucket, "key": key})
            except (BotoCoreError, ObjectStorageError, HTTPError) as exc:
                failures.append({"resource": "storage", "error_type": type(exc).__name__})
        return failures

    async def _cleanup_standard_bucket(self):
        from botocore.exceptions import BotoCoreError, ClientError
        from httpx import HTTPError
        from storage3.exceptions import StorageException
        from app.services.object_storage import ObjectStorageError
        from workspace_resource_cleanup import (
            WorkspaceBucketCleanupError,
            remove_empty_standard_bucket,
        )

        if not self.observation.storage_keys:
            return []
        try:
            if self.vector_runtime is None:
                raise WorkspaceBucketCleanupError("Storage runtime is unavailable")
            result = await remove_empty_standard_bucket(
                schema=self.schema,
                storage_inventory=tuple(self.observation.storage_keys),
                storage=self.vector_runtime.storage,
            )
            self.report["standard_bucket_cleanup"] = result
            self.observation.assertion(
                "exact_standard_bucket_removed", result["verified_absent"], bucket=result["bucket"]
            )
        except (
            BotoCoreError,
            ClientError,
            HTTPError,
            StorageException,
            ObjectStorageError,
            WorkspaceBucketCleanupError,
        ) as exc:
            self.observation.assertion("exact_standard_bucket_removed", False)
            return [{"resource": "standard_bucket", "error_type": type(exc).__name__}]
        return []

    async def cleanup(self):
        from sqlalchemy import text

        failures = await self._cleanup_vectors()
        failures.extend(await self._cleanup_storage())
        failures.extend(await self._cleanup_standard_bucket())
        self.observation.close()
        if self.vector_runtime:
            await self.vector_runtime.close()
        if self.engine:
            await self.engine.dispose()
        if self.admin_engine:
            async with self.admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
                exists = await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.schemata WHERE schema_name=:schema"
                    ),
                    {"schema": self.schema},
                )
            self.observation.assertion("isolated_schema_removed", exists == 0)
            await self.admin_engine.dispose()
        self.report["cleanup_failures"] = failures
        if failures or any(not row["passed"] for row in self.report["assertions"]):
            self.report["status"] = "failed_assertions"
        self.observation.save()


async def serve(report_path: Path):
    import uvicorn

    runtime = LiveRuntime(report_path)
    try:
        await runtime.start()
        from app.services import jobs

        jobs.set_schedule_hook(None)

        # Browser receives only a short-lived fixture token, never service credentials.
        @runtime.app.get("/__workspace_fixture", include_in_schema=False)
        async def fixture():
            return {"access_token": runtime.token(), "email": runtime.email}

        @asynccontextmanager
        async def isolated_lifespan(_app):
            yield

        runtime.app.router.lifespan_context = isolated_lifespan
        print("Isolated workspace backend ready at http://127.0.0.1:8317", flush=True)
        server = uvicorn.Server(
            uvicorn.Config(runtime.app, host="127.0.0.1", port=8317, log_level="warning")
        )

        @runtime.app.post("/__workspace_shutdown", include_in_schema=False)
        async def shutdown():
            server.should_exit = True
            return {"status": "stopping"}

        await server.serve()
    finally:
        await runtime.cleanup()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument(
        "--report", type=Path, default=REPO / "integration-tests/workspace-browser-live.json"
    )
    arguments = parser.parse_args()
    asyncio.run(serve(arguments.report))
