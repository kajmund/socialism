"""Real-process verification: two FastAPI backends + one Overgraph owner.

Starts the actual app under uvicorn in separate OS processes, a separate owner
process, shares one SQLite database and one Overgraph catalog, performs real
document ingest through the HTTP API in both backends, and verifies the graph
through the owner (and through a fresh catalog handle after the owner stops).

Only truly external boundaries are replaced in the backend processes: object
storage (shared filesystem) and OpenAI embeddings (deterministic fake). The
owner, API, ingest job, SQL persistence and graph writes are real.

Usage:
    cd backend
    .venv/bin/python scripts/verify_owner_multiprocess_fastapi.py --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.services.overgraph.owner import OwnerClient, OwnerUnavailable

BACKEND = Path(__file__).resolve().parents[1]
LAUNCHER = Path(__file__).resolve().with_name("owner_test_backend.py")
DIMENSION = 3072
EMBEDDING_MODEL = "text-embedding-3-large"
LOCAL_SECRET = "owner-multiprocess-test-secret-32bytes"
OWNER_READY_TIMEOUT = 30
HTTP_TIMEOUT = 30


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _base_env(root: Path, *, owner_id: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'app.sqlite'}",
        "CEREBRAS_API_KEY": "test-key",
        "OPENAI_API_KEY": "test-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role",
        "LOCAL_AUTH_JWT_SECRET": LOCAL_SECRET,
        "ALLOW_LOCAL_LOGIN": "true",
        "OVERGRAPH_DIR": str(root / "overgraph"),
        "OVERGRAPH_OWNER_SOCKET": str(root / "owner.sock"),
        "OVERGRAPH_OWNER_CATALOG_ID": owner_id or "",
        "EMBEDDING_MODEL": EMBEDDING_MODEL,
        "EMBEDDING_DIMENSION": str(DIMENSION),
        "RESEARCH_WORKER_LOOP_ENABLED": "false",
        "GRAPH_INGEST_LOOP_ENABLED": "false",
        "LOG_DIR": "",
        "LOGSTASH_URL": "",
        "LOGSTASH_USERNAME": "",
        "LOGSTASH_PASSWORD": "",
        "OWNER_TEST_STORAGE_DIR": str(root / "objects"),
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _run(cmd: list[str], env: dict[str, str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, env=env, cwd=BACKEND, capture_output=True, text=True, **kwargs,
    )


def _create_database(env: dict[str, str]) -> None:
    code = (
        "import asyncio\n"
        "import app.database.models\n"
        "from app.database.base import Base\n"
        "from app.database.session import engine\n"
        "async def main():\n"
        "    async with engine.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "    await engine.dispose()\n"
        "asyncio.run(main())\n"
    )
    result = _run([sys.executable, "-c", code], env)
    if result.returncode != 0:
        raise RuntimeError(f"database setup failed: {result.stderr[-3000:]}")


def _seed_clause_catalog(env: dict[str, str]) -> dict[str, Any]:
    """Seed classification + TextUnits before the owner starts (setup only).

    Clause decisions themselves are made through the real HTTP API on both
    backends above. Seeding directly is safe because the owner is not running
    yet and the setup process closes the catalog before it starts.
    """
    code = """
import json
from pathlib import Path
from app.services.overgraph.catalogs import open_catalog
from app.services.knowledge.scope import shared_scope
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.write import upsert_text_unit
from app.services.clause_ssr.classifications import upsert_classification

root = Path(__import__('os').environ['OVERGRAPH_DIR'])
catalog = open_catalog(root / 'knowledge', kind='knowledge', dimension=int(__import__('os').environ['EMBEDDING_DIMENSION']))
scope = shared_scope()
classification = upsert_classification(
    catalog, scope=scope, slug='termination',
    question='Ar det en uppsagningstid?', category='termination',
)
units = []
for index in range(4):
    unit = TextUnitWrite(
        unit_id=f'clause-unit-{index}', scope=scope, document_id='clause-doc',
        document_version_id='clause-ver', text=f'Klausul {index}', content_hash=f'hash-{index}',
        ordinal=index,
    )
    upsert_text_unit(catalog, unit)
    units.append(unit.unit_id)
catalog.close()
print(json.dumps({'classification_id': classification.id, 'unit_ids': units}))
"""
    result = _run([sys.executable, "-c", code], env)
    if result.returncode != 0:
        raise RuntimeError(f"clause seed failed: {result.stderr[-3000:]}")
    return dict(json.loads(result.stdout.strip().splitlines()[-1]))


class Process:
    def __init__(
        self, name: str, argv: list[str], env: dict[str, str], log: Path,
        *, port: int | None = None,
    ) -> None:
        self.name = name
        self.log = log
        self.port = port
        self._handle = log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            argv, cwd=BACKEND, env=env,
            stdout=self._handle, stderr=subprocess.STDOUT,
        )

    @property
    def pid(self) -> int:
        return int(self.proc.pid)

    def stop(self, *, sig: int = signal.SIGTERM) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(sig)
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self._handle.close()

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=10)
        self._handle.close()

    def output(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")[-4000:]
        except FileNotFoundError:
            return ""


def _start_owner(root: Path, *, sync: bool = True) -> Process:
    argv = [
        sys.executable, "-m", "app.services.overgraph.owner",
        str(root / "overgraph" / "knowledge"),
        "--socket", str(root / "owner.sock"),
        "--dimension", str(DIMENSION),
    ]
    if not sync:
        argv.append("--no-sync")
    process = Process("owner", argv, _base_env(root, owner_id=None), root / "owner.log")
    _wait_owner_ready(root / "owner.sock")
    return process


def _wait_owner_ready(socket_path: Path) -> None:
    deadline = time.monotonic() + OWNER_READY_TIMEOUT
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            asyncio.run(OwnerClient(socket_path).health())
            return
        except (OwnerUnavailable, OSError, ConnectionError) as exc:
            last = exc
            time.sleep(0.05)
    raise TimeoutError(f"owner at {socket_path} did not become ready: {last}")


def _owner_id(root: Path) -> str:
    identity = root / "overgraph" / ".knowledge.overgraph-owner-id"
    _wait_file(identity, timeout=OWNER_READY_TIMEOUT)
    return identity.read_text(encoding="utf-8").strip()


def _wait_file(path: Path, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise TimeoutError(f"{path} did not appear")


def _http(
    method: str, url: str, *, token: str | None = None,
    body: bytes | None = None, headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = {"detail": payload.decode("utf-8", "replace")}
        return exc.code, decoded


def _wait_http(url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = _http("GET", url, timeout=2)
            if status == 200:
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f"{url} did not become ready")


def _start_backend(
    root: Path, *, port: int, owner_id: str, guard: Path, sync_on_commit: bool = True,
) -> Process:
    del sync_on_commit  # owner-side setting; kept for call-site clarity
    env = _base_env(root, owner_id=owner_id)
    env["OWNER_TEST_GUARD_FILE"] = str(guard)
    env["OWNER_TEST_NO_LOCAL_KNOWLEDGE"] = "1"
    process = Process(
        f"backend-{port}",
        [sys.executable, str(LAUNCHER), str(port)],
        env, root / f"backend-{port}.log", port=port,
    )
    _wait_http(f"http://127.0.0.1:{port}/health", timeout=60)
    return process


def _login(port: int) -> str:
    status, payload = _http(
        "POST", f"http://127.0.0.1:{port}/auth/local-login", body=b"",
        headers={"Content-Type": "application/json"},
    )
    if status != 200:
        raise RuntimeError(f"local login failed: {status} {payload}")
    return str(payload["access_token"])


def _upload(port: int, token: str, filename: str, text: str) -> dict[str, Any]:
    boundary = "----owner-test-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    status, payload = _http(
        "POST", f"http://127.0.0.1:{port}/underlag?module=dd", token=token, body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    if status != 201:
        raise RuntimeError(f"upload failed: {status} {payload}")
    return dict(payload)


def _wait_job(port: int, token: str, job_id: str, *, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = _http("GET", f"http://127.0.0.1:{port}/jobs/{job_id}", token=token)
        if status == 200 and payload.get("status") not in {"pending", "running"}:
            return dict(payload)
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} did not finish")


def _owner_query(
    port: int, token: str, label: str, *, props: dict[str, str] | None = None,
    include_vectors: bool = False, limit: int = 100,
) -> dict[str, Any]:
    status, payload = _http(
        "POST", f"http://127.0.0.1:{port}/overgraph/knowledge/query",
        token=token,
        body=json.dumps({
            "label": label, "props": props or {}, "include_vectors": include_vectors,
            "limit": limit,
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert status == 200, (status, payload)
    assert payload.get("access") == "owner", payload
    return dict(payload)


def _owner_status(port: int) -> dict[str, Any]:
    status, payload = _http("GET", f"http://127.0.0.1:{port}/health/overgraph-owner")
    if status != 200:
        raise RuntimeError(f"owner health failed: {status} {payload}")
    return dict(payload)


def _read_owner_units(socket_path: Path, version_id: str) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        client = OwnerClient(socket_path)
        return await client.list_nodes(
            "TextUnit", props={"document_version_id": version_id},
            include_vectors=True, limit=20_000,
        )

    return asyncio.run(run())


def _wait_owner_vectors(
    socket_path: Path, version_id: str, chunks: int, *, timeout: float = 60,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    rows: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        try:
            rows = _read_owner_units(socket_path, version_id)
        except (OwnerUnavailable, OSError):
            rows = []
        if len(rows) >= chunks and all(row.get("dense_vector") for row in rows):
            return rows
        time.sleep(0.2)
    raise TimeoutError(
        f"version {version_id}: expected {chunks} embedded units, got "
        f"{len(rows)} (vectors={sum(1 for row in rows if row.get('dense_vector'))})"
    )


def _snapshot_graph(root: Path) -> dict[str, Any]:
    """Read the catalog directly after the owner has stopped (read-only check)."""
    from app.services.overgraph.catalogs import open_catalog

    catalog = open_catalog(root / "overgraph" / "knowledge", kind="knowledge", dimension=DIMENSION)
    try:
        units, _ = catalog.query_nodes(
            label_filter={"labels": ["TextUnit"], "mode": "all"}, limit=10_000,
        )
        versions, _ = catalog.query_nodes(
            label_filter={"labels": ["DocumentVersion"], "mode": "all"}, limit=10_000,
        )
        return {
            "text_units": len(units),
            "with_vectors": sum(1 for row in units if row.dense_vector),
            "document_versions": len(versions),
            "contains_edges": catalog.count_edges_by_label("CONTAINS"),
            "next_edges": catalog.count_edges_by_label("NEXT"),
            "receipts": catalog.count_nodes_by_labels(["MutationReceipt"]),
            "verifications": catalog.count_nodes_by_labels(["SsrVerification"]),
            "review_sessions": catalog.count_nodes_by_labels(["SsrReviewSession"]),
        }
    finally:
        catalog.close()


def _guard_lines(guard: Path) -> list[str]:
    if not guard.exists():
        return []
    return [line for line in guard.read_text(encoding="utf-8").splitlines() if line.strip()]


def scenario_two_backends(root: Path) -> dict[str, Any]:  # noqa: C901, PLR0915
    seeded = _seed_clause_catalog(_base_env(root, owner_id=None))
    owner = _start_owner(root)
    backends: list[Process] = []
    guard_a = root / "guard-a.log"
    guard_b = root / "guard-b.log"
    try:
        owner_id = _owner_id(root)
        port_a, port_b = _free_port(), _free_port()
        backend_a = _start_backend(root, port=port_a, owner_id=owner_id, guard=guard_a)
        backend_b = _start_backend(root, port=port_b, owner_id=owner_id, guard=guard_b)
        backends = [backend_a, backend_b]
        status_a = _owner_status(port_a)
        status_b = _owner_status(port_b)
        assert status_a["status"] == "ready" and status_a["catalog_id"] == owner_id
        assert status_b["status"] == "ready" and status_b["catalog_id"] == owner_id
        assert status_a["write_paths_ready"] is False
        assert status_b["write_paths_ready"] is False

        token = _login(port_a)
        assert _http("GET", f"http://127.0.0.1:{port_b}/me", token=token)[0] == 200

        uploads: dict[str, dict[str, Any]] = {}
        started = time.perf_counter()

        def upload(port: int, filename: str, text: str) -> None:
            uploads[filename] = _upload(port, token, filename, text)

        threads = [
            threading.Thread(
                target=upload,
                args=(port_a, "avtal-a.txt", "Avtalet har nio månaders uppsägningstid."),
            ),
            threading.Thread(
                target=upload,
                args=(port_b, "avtal-b.txt", "Betalning sker inom trettio dagar."),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        dispatch_seconds = round(time.perf_counter() - started, 3)

        results: dict[str, Any] = {}
        for filename, uploaded in uploads.items():
            port = port_a if filename == "avtal-a.txt" else port_b
            job = _wait_job(port, token, str(uploaded["knowledge_job_id"]))
            assert job["status"] == "succeeded", job
            payload = dict(job["result"] or {})
            version_id = str(payload["document_version_id"])
            chunks = int(payload["chunks_indexed"])
            rows = _wait_owner_vectors(root / "owner.sock", version_id, chunks)
            assert len(rows) == chunks, (filename, len(rows), chunks)
            assert {row["props"]["document_version_id"] for row in rows} == {version_id}
            # Backend B must read A's committed units through the owner API,
            # without ever opening the knowledge catalog itself.
            read_back = _owner_query(
                port_b, token, "TextUnit",
                props={"document_version_id": version_id},
                include_vectors=True, limit=100,
            )
            assert len(read_back["nodes"]) == chunks, read_back
            for node in read_back["nodes"]:
                assert node["props"]["document_version_id"] == version_id
                assert node["props"]["text"]
                assert len(node["dense_vector"]) == DIMENSION
            results[filename] = {
                "port": port,
                "document_id": payload["document_id"],
                "document_version_id": version_id,
                "chunks": chunks,
                "vectors": sum(1 for row in rows if row.get("dense_vector")),
                "locators": sorted(row["props"]["locator"] for row in rows),
            }
        ingest_seconds = round(time.perf_counter() - started, 3)

        # A publishes a frozen answer through the production owner writer; B
        # must find and reuse it via its owner-backed authoritative lookup.
        published = _http(
            "POST", f"http://127.0.0.1:{port_a}/__owner_test__/publish-answer",
            body=json.dumps({
                "question_id": "question-reuse-cross-process",
                "question_text": "Vad gäller uppsägningstiden?",
                "customer_id": 1,
                "identity": "answer-reuse-cross-process",
                "evidence_set_id": "evidence-set-reuse-cross-process",
                "attributes": {
                    "knowledge_module": "dd", "knowledge_case_id": None,
                    "workspace_id": None, "document_version_ids": [],
                    "answer_status": "sufficient",
                },
                "basis": [{
                    "evidence_id": "evidence-reuse-cross-process",
                    "research_need_id": "need-reuse-cross-process",
                    "source_type": "document", "status": "found",
                    "title": "Uppsägningstid", "excerpt": "Nio månader",
                    "locator": "sida 1", "source_id": "doc-reuse-cross-process",
                    "source_url": None, "provider": "uploaded_file", "score": 1.0,
                    "retrieved_at": time.strftime(
                        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(),
                    ),
                    "metadata": {"reuse": {"evidence_ref": "doc-reuse:1"}},
                }],
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert published[0] == 200, published
        reused = _http(
            "POST", f"http://127.0.0.1:{port_b}/__owner_test__/lookup-answers",
            body=json.dumps({
                "need_id": "need-reuse-cross-process",
                "question": "Vad gäller uppsägningstiden?",
                "question_id": "question-reuse-cross-process",
                "customer_id": 1, "module": "dd",
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert reused[0] == 200, reused
        evidence = reused[1]["evidence"]
        assert len(evidence) == 1, evidence
        assert evidence[0]["source_id"] == "doc-reuse-cross-process"
        assert evidence[0]["metadata"]["answer_fact_id"] == published[1]["fact_id"]

        # Real owner-backed knowledge writes from both API processes: clause
        # decisions on different units through the same owner.
        me = _http("GET", f"http://127.0.0.1:{port_a}/me", token=token)[1]
        reviewer_id = str(me["id"])
        decisions: list[dict[str, Any]] = []

        def decide(port: int, unit_id: str) -> None:
            status, payload = _http(
                "POST", f"http://127.0.0.1:{port}/clause-ssr/decisions",
                token=token,
                body=json.dumps({
                    "classification_id": seeded["classification_id"],
                    "unit_id": unit_id,
                    "answer": "yes",
                    # One session per unit: decisions in the same reviewer
                    # session are serialized by the UI, so this exercises owner
                    # serialization without a domain-level session race.
                    "document_id": f"clause-doc-{unit_id}",
                }).encode(),
                headers={"Content-Type": "application/json"},
            )
            decisions.append({"status": status, "payload": payload, "port": port})

        decision_threads = [
            threading.Thread(target=decide, args=(port_a, seeded["unit_ids"][0])),
            threading.Thread(target=decide, args=(port_a, seeded["unit_ids"][1])),
            threading.Thread(target=decide, args=(port_b, seeded["unit_ids"][2])),
            threading.Thread(target=decide, args=(port_b, seeded["unit_ids"][3])),
        ]
        for thread in decision_threads:
            thread.start()
        for thread in decision_threads:
            thread.join(timeout=60)
        assert [row["status"] for row in decisions] == [200, 200, 200, 200], decisions
        assert len({row["payload"]["verification"]["id"] for row in decisions}) == 4
        assert reviewer_id

        def _owner_count(label: str) -> int:
            async def run() -> int:
                return len(await OwnerClient(root / "owner.sock").list_nodes(label))

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if asyncio.run(run()) >= 4:
                    break
                time.sleep(0.1)
            return asyncio.run(run())

        assert _owner_count("SsrVerification") == 4
        assert _owner_count("SsrReviewSession") == 4

        # Update and revoke are visible to the other backend through the owner.
        updated = _http(
            "POST", f"http://127.0.0.1:{port_a}/clause-ssr/decisions", token=token,
            body=json.dumps({
                "classification_id": seeded["classification_id"],
                "unit_id": seeded["unit_ids"][0], "answer": "no",
                "document_id": f"clause-doc-{seeded['unit_ids'][0]}",
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert updated[0] == 200, updated
        verification_read = _owner_query(
            port_b, token, "SsrVerification",
            props={"source_unit_id": seeded["unit_ids"][0]}, limit=10,
        )["nodes"]
        assert [node["props"]["answer"] for node in verification_read] == ["no"]
        undo = _http(
            "POST", f"http://127.0.0.1:{port_a}/clause-ssr/decisions/undo", token=token,
            body=json.dumps({
                "classification_id": seeded["classification_id"],
                "document_id": f"clause-doc-{seeded['unit_ids'][0]}",
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert undo[0] == 200, undo
        revoked = _owner_query(
            port_b, token, "SsrVerification",
            props={"source_unit_id": seeded["unit_ids"][0]}, limit=10,
        )["nodes"]
        assert [node["props"]["status"] for node in revoked] == ["revoked"]

        # Owner restart keeps the same data readable from both backends.
        first_version = next(iter(results.values()))["document_version_id"]
        owner.stop()
        owner = None
        owner = _start_owner(root)
        assert _owner_status(port_b)["status"] == "ready"
        restarted = _owner_query(
            port_b, token, "TextUnit",
            props={"document_version_id": first_version}, include_vectors=True,
        )
        assert len(restarted["nodes"]) >= 1

        assert not _guard_lines(guard_a), _guard_lines(guard_a)
        assert not _guard_lines(guard_b), _guard_lines(guard_b)

        for backend in backends:
            backend.stop()
        backends = []
        owner.stop()
        owner = None
        snapshot = _snapshot_graph(root)
        assert snapshot["text_units"] >= sum(row["chunks"] for row in results.values())
        assert snapshot["with_vectors"] >= sum(row["chunks"] for row in results.values())
        assert snapshot["contains_edges"] >= len(results)
        assert snapshot["verifications"] == 4
        assert snapshot["review_sessions"] == 4
        return {
            "owner_id": owner_id,
            "owner_status": {"a": status_a, "b": status_b},
            "dispatch_seconds": dispatch_seconds,
            "ingest_seconds": ingest_seconds,
            "documents": results,
            "answer_reuse": {
                "fact_id": published[1]["fact_id"],
                "evidence_count": len(evidence),
            },
            "clause_decisions": len(decisions),
            "graph_after_owner_stop": snapshot,
            "direct_write_attempts": 0,
        }
    finally:
        for backend in backends:
            if backend.proc.poll() is None:
                backend.stop()
        if owner is not None:
            owner.stop()


def scenario_lifecycle_and_outage(root: Path) -> dict[str, Any]:  # noqa: PLR0915
    """Backend before owner, owner outage, reconnect, wrong catalog identity."""
    # The backend needs the owner socket path before the owner exists.
    port = _free_port()
    backend = _start_backend(root, port=port, owner_id="", guard=root / "guard-life.log")
    observations: dict[str, Any] = {}
    owner = None
    try:
        token = _login(port)
        observations["before_owner"] = _owner_status(port)
        assert observations["before_owner"]["status"] == "unavailable"
        uploaded = _upload(port, token, "fore-owner.txt", "Utan owner får ingen skrivning ske.")
        job = _wait_job(port, token, str(uploaded["knowledge_job_id"]))
        assert job["status"] == "failed", job
        observations["write_without_owner"] = {
            "status": job["status"], "error": str(job.get("error") or "")[:200],
        }
        assert not _guard_lines(root / "guard-life.log")

        owner = _start_owner(root)
        observations["after_owner_start"] = _owner_status(port)
        assert observations["after_owner_start"]["status"] == "ready"
        uploaded = _upload(port, token, "med-owner.txt", "Nu finns owner och skrivningen går igenom.")
        job = _wait_job(port, token, str(uploaded["knowledge_job_id"]))
        assert job["status"] == "succeeded", job
        version = str((job["result"] or {})["document_version_id"])
        _wait_owner_vectors(root / "owner.sock", version, 1)
        observations["after_reconnect"] = {"job": job["status"], "chunks": (job["result"] or {}).get("chunks_indexed")}

        owner.stop()
        observations["after_owner_stop"] = _owner_status(port)
        assert observations["after_owner_stop"]["status"] == "unavailable"
        uploaded = _upload(port, token, "owner-nere.txt", "Owner är nere och får inte fallbacka.")
        job = _wait_job(port, token, str(uploaded["knowledge_job_id"]))
        assert job["status"] == "failed", job
        observations["write_after_owner_stop"] = {"status": job["status"]}
        assert not _guard_lines(root / "guard-life.log")

        owner = _start_owner(root)
        assert _owner_status(port)["status"] == "ready"
        uploaded = _upload(port, token, "efter-omstart.txt", "Owner är tillbaka och arbetet fortsätter.")
        job = _wait_job(port, token, str(uploaded["knowledge_job_id"]))
        assert job["status"] == "succeeded", job
        observations["after_owner_restart"] = {"job": job["status"]}

        wrong_port = _free_port()
        wrong = _start_backend(
            root, port=wrong_port, owner_id="wrong-catalog-id", guard=root / "guard-wrong.log",
        )
        try:
            wrong_status = _owner_status(wrong_port)
            assert wrong_status["status"] == "unavailable"
            observations["wrong_catalog"] = wrong_status
            wrong_token = _login(wrong_port)
            uploaded = _upload(
                wrong_port, wrong_token,
                "fel-katalog.txt", "Fel katalogidentitet ska avvisas.",
            )
            job = _wait_job(
                wrong_port, wrong_token, str(uploaded["knowledge_job_id"]),
            )
            assert job["status"] == "failed", job
            observations["wrong_catalog_write"] = {"status": job["status"]}
            assert not _guard_lines(root / "guard-wrong.log")
        finally:
            wrong.stop()
        return {"observations": observations}
    finally:
        if backend.proc.poll() is None:
            backend.stop()
        if owner is not None:
            owner.stop()


def scenario_exclusive_owner_and_restart_receipt(root: Path) -> dict[str, Any]:
    owner = _start_owner(root)
    try:
        owner_id = _owner_id(root)
        assert owner_id
        second_socket = root / "second-owner.sock"
        second = subprocess.run(
            [
                sys.executable, "-m", "app.services.overgraph.owner",
                str(root / "overgraph" / "knowledge"),
                "--socket", str(second_socket),
                "--dimension", str(DIMENSION),
            ],
            cwd=BACKEND, env=_base_env(root, owner_id=None),
            capture_output=True, text=True, timeout=30,
        )
        assert second.returncode != 0, "second owner must not own the same catalog"
        assert "already owned" in (second.stderr + second.stdout).lower()

        socket_path = root / "owner.sock"

        class LossyClient(OwnerClient):
            def __init__(self) -> None:
                super().__init__(socket_path, catalog_id=owner_id)
                self.lost = False
                self.sent: tuple[str, dict[str, Any]] | None = None

            async def mutate(self, mutation_id, patch, *, kind="patch"):
                response = await super().mutate(mutation_id, patch, kind=kind)
                if not self.lost:
                    self.lost = True
                    self.sent = (mutation_id, patch)
                    raise OwnerUnavailable("response lost after commit")
                return response

        client = LossyClient()
        patch = {"upsert_nodes": [{
            "labels": ["HardeningProbe", "owner-test"],
            "key": "restart-probe",
            "props": {"value": 1},
        }]}
        result = asyncio.run(client.mutate_with_retry(
            "hardening-restart-1", patch, kind="batch", attempts=3, delay=0.0,
        ))
        assert result.get("ok") is True and result.get("duplicate") is True
        assert client.sent is not None
        mutation_id, committed_patch = client.sent
        owner.stop()
        owner = None
        owner = _start_owner(root)
        replay = asyncio.run(OwnerClient(socket_path).mutate(
            mutation_id, committed_patch, kind="batch",
        ))
        assert replay.get("ok") is True and replay.get("duplicate") is True
        rows = asyncio.run(OwnerClient(socket_path).list_nodes("HardeningProbe"))
        assert len(rows) == 1
        return {
            "exclusive_second_owner": "rejected",
            "transport_retry_duplicate": True,
            "restart_replay_duplicate": True,
            "probe_nodes": len(rows),
            "mutation_id": mutation_id,
        }
    finally:
        if owner is not None:
            owner.stop()


def scenario_durable_ack(root: Path) -> dict[str, Any]:
    owner = _start_owner(root, sync=True)
    try:
        socket_path = root / "owner.sock"
        started = time.perf_counter()
        asyncio.run(OwnerClient(socket_path).mutate(
            "durable-ack-1",
            {"upsert_nodes": [{
                "labels": ["HardeningProbe", "owner-test"],
                "key": "durable-node",
                "props": {"value": "acked"},
            }]},
            kind="batch",
        ))
        ack_seconds = round(time.perf_counter() - started, 4)
        health = asyncio.run(OwnerClient(socket_path).health())
        assert health["sync_on_commit"] is True
        assert health["metrics"]["sync_seconds"], "durable mode must sync before ack"
        owner.kill()  # SIGKILL: no close(), no flush on shutdown
        owner = _start_owner(root)
        rows = asyncio.run(OwnerClient(socket_path).list_nodes("HardeningProbe"))
        assert len(rows) == 1, "acked mutation was lost after SIGKILL"
        return {
            "ack_seconds": ack_seconds,
            "sync_samples": health["metrics"]["sync_seconds"][-3:],
            "survived_sigkill": True,
        }
    finally:
        if owner is not None:
            owner.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="", help="write the report JSON here")
    parser.add_argument("--keep", action="store_true", help="keep the temp directory")
    args = parser.parse_args()
    base = Path(tempfile.mkdtemp(prefix="owner-fastapi-"))
    report: dict[str, Any] = {"root": str(base), "scenarios": {}}
    try:
        for name, scenario in (
            ("two_backends", scenario_two_backends),
            ("exclusive_owner_restart_receipt", scenario_exclusive_owner_and_restart_receipt),
            ("durable_ack", scenario_durable_ack),
            ("lifecycle_and_outage", scenario_lifecycle_and_outage),
        ):
            # One catalog per scenario: OverGraph does not support several
            # processes opening one catalog, so scenarios must not share one.
            # Short temp paths: AF_UNIX socket paths are length-limited.
            root = Path(tempfile.mkdtemp(prefix=f"owner-{name[:6]}-"))
            report.setdefault("scenario_roots", {})[name] = str(root)
            _create_database(_base_env(root, owner_id=None))
            started = time.perf_counter()
            try:
                report["scenarios"][name] = {
                    "ok": True,
                    "seconds": 0.0,
                    "result": scenario(root),
                }
            except Exception as exc:  # report, don't hide other scenarios
                report["scenarios"][name] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "log": _tail_logs(root),
                }
                raise
            finally:
                report["scenarios"][name]["seconds"] = round(
                    time.perf_counter() - started, 3,
                )
    finally:
        if not args.keep:
            pass
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


def _tail_logs(root: Path) -> str:
    chunks = []
    for path in sorted(root.glob("*.log")):
        chunks.append(f"--- {path.name}\n{path.read_text(encoding='utf-8', errors='replace')[-3000:]}")
    return "\n".join(chunks)[-6000:]


if __name__ == "__main__":
    raise SystemExit(main())
