"""Additional live-orchestration fixtures layered onto the Step A database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.models import Persona
from app.database.stored_objects import StoredObject
from app.services.prompt_store import ensure_default_configurations
from scripts.document_presentation_benchmark.cases import (
    DOCUMENT_TYPES,
    fixture_inventory,
)
from scripts.document_presentation_benchmark.environment import (
    CONTAINER_ID,
    CUSTOMER_ID,
    USER_ID,
    create_environment,
)
from scripts.document_presentation_benchmark.step_b_types import CHANNELS
from scripts.document_presentation_benchmark.types import BenchmarkEnvironment, GoldCase

EXPERT_PROFILE = {
    "name": "Benchmarkjuristen",
    "age": "45",
    "occupation": "Avtalsjurist",
    "location": "Stockholm",
}


async def create_step_b_environment(
    root: Path,
    cases: list[GoldCase],
) -> tuple[BenchmarkEnvironment, Any]:
    environment, engine = await create_environment(root)
    async with environment.sessions() as session:
        await ensure_default_configurations(session)
        _seed_sources(session)
        _seed_personas(session, cases)
        await session.commit()
    return environment, engine


def persona_id(case: GoldCase, channel: str) -> str:
    return f"step-b-{case.case_id}-{channel}".replace("_", "-")


def _seed_personas(session, cases: list[GoldCase]) -> None:
    for case in cases:
        for channel in CHANNELS:
            session.add(
                Persona(
                    id=persona_id(case, channel),
                    customer_id=CUSTOMER_ID,
                    kind="expert",
                    name="Benchmarkjuristen",
                    age=45,
                    occ="Avtalsjurist",
                    district="Stockholm",
                    quote="",
                    origin="benchmark",
                    profile=EXPERT_PROFILE,
                    tools=[],
                )
            )


def _seed_sources(session) -> None:
    inventory = fixture_inventory()
    labels = dict(
        zip(
            DOCUMENT_TYPES,
            (
                "Hyresavtal",
                "Anställningsavtal",
                "Konsultavtal",
                "Sekretessavtal",
                "Leveransavtal",
            ),
            strict=True,
        )
    )
    for document_type, source_ids in inventory.items():
        for ordinal, source_id in enumerate(source_ids):
            session.add(
                StoredObject(
                    id=source_id,
                    workspace_id=CONTAINER_ID,
                    customer_id=CUSTOMER_ID,
                    owner_user_id=USER_ID,
                    module="dd",
                    kind="underlag",
                    bucket="benchmark",
                    object_key=f"{source_id}.pdf",
                    filename=f"{labels[document_type]} {ordinal + 1}.pdf",
                    content_type="application/pdf",
                    size_bytes=1,
                    extraction_status="ready",
                    knowledge_status="ready",
                )
            )

