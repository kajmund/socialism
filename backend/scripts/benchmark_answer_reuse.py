"""Measure owner-socket transport for authoritative answer reuse."""

from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.knowledge_scope import customer_scope
from app.services.knowledge.models import KnowledgeScope
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_facts import publish_answer_via_owner
from app.services.overgraph.publish import AnswerPublish
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.research.answer_graph import lookup_answers
from app.services.research.models import ResearchContext, ResearchNeed

BACKEND = Path(__file__).resolve().parents[1]
SIZES = (1, 10, 100)
REPEATS = 10


def _spawn(root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable, "-m", "app.services.overgraph.owner",
            str(root / "catalog"), "--socket", str(root / "owner.sock"),
            "--dimension", "4", "--no-sync",
        ],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
    )


async def _start(root: Path) -> tuple[subprocess.Popen[str], OwnerClient]:
    process = _spawn(root)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            client = OwnerClient(root / "owner.sock")
            await client.health()
            return process, client
        except Exception:  # noqa: BLE001 - startup waiter
            await asyncio.sleep(0.05)
    process.kill()
    raise TimeoutError("owner did not start")


def _evidence(now: datetime, count: int) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        rows.append({
            "evidence_id": f"evidence-{index}",
            "research_need_id": "need-bench",
            "source_type": "document",
            "status": "found",
            "title": f"Source {index}",
            "excerpt": "x" * 180,
            "locator": f"sida {index}",
            "source_id": f"doc-{index}",
            "source_url": None,
            "provider": "uploaded_file",
            "score": 1.0,
            "retrieved_at": now.isoformat(),
            "metadata": {"reuse": {"evidence_ref": f"doc-{index}:1"}},
        })
    return rows


async def _measure(client: OwnerClient, session: AsyncSession, count: int, index: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    published = AnswerPublish(
        question_id=f"question-bench-{count}-{index}",
        question_text="Benchmark answer reuse",
        scope=customer_scope(1),
        identity=f"answer-bench-{count}-{index}",
        evidence_set_id=f"evidence-set-bench-{count}-{index}",
        attributes={
            "knowledge_module": "dd", "knowledge_case_id": None,
            "workspace_id": None, "document_version_ids": [],
            "answer_status": "sufficient",
        },
        basis=_evidence(now - timedelta(seconds=1), count),
        assessment={"sufficient": True},
        dependency_ids=(),
    )
    await publish_answer_via_owner(client, published)
    before = (await client.health())["metrics"]
    started = time.perf_counter()
    found = await lookup_answers(
        session,
        need=ResearchNeed(
            id="need-bench", question="Benchmark answer reuse", why_needed="",
            source_types=["document"],
            knowledge_question_id=published.question_id,
        ),
        context=ResearchContext(scope=KnowledgeScope(customer_id=1, module="dd")),
        now=now + timedelta(seconds=1),
    )
    elapsed = time.perf_counter() - started
    after = (await client.health())["metrics"]
    assert len(found) == count
    return {
        "evidence": count,
        "seconds": round(elapsed, 5),
        "read_ops": after["read_ops"] - before["read_ops"],
        "read_bytes": after["read_bytes"] - before["read_bytes"],
        "read_objects": after["read_objects"] - before["read_objects"],
    }


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="owner-answer-bench-"))
    owner, client = await _start(root)
    get_owner_runtime().client = client
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            report = {}
            for count in SIZES:
                samples = [
                    await _measure(client, session, count, index)
                    for index in range(REPEATS)
                ]
                report[str(count)] = {
                    "reads": samples,
                    "median_seconds": round(statistics.median(
                        sample["seconds"] for sample in samples
                    ), 5),
                    "median_read_ops": statistics.median(
                        sample["read_ops"] for sample in samples
                    ),
                    "median_read_bytes": statistics.median(
                        sample["read_bytes"] for sample in samples
                    ),
                }
        print(json.dumps(report, indent=2))
        return 0
    finally:
        owner.terminate()
        try:
            owner.wait(timeout=10)
        except subprocess.TimeoutExpired:
            owner.kill()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
