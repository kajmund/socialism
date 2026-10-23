"""Fixtures for the isolated clause SSR library."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.text_units import upsert_text_units
from app.services.clause_ssr.types import EmbeddingSpec

DIM = 32


def embedding_spec() -> EmbeddingSpec:
    return EmbeddingSpec(model="text-embedding-3-large", revision="v1", dimension=DIM)


def unit_vector(index: int) -> list[float]:
    vector = [0.0] * DIM
    vector[index % DIM] = 1.0
    return vector


def near_vector(index: int, drift: float = 0.15) -> list[float]:
    vector = unit_vector(index)
    neighbor = (index + 1) % DIM
    vector[index % DIM] = 1.0 - drift
    vector[neighbor] = drift
    return vector


def make_unit(
    *,
    unit_id: str,
    text: str,
    document_id: str = "doc-1",
    version_id: str = "ver-1",
    ordinal: int = 0,
) -> TextUnit:
    return TextUnit(
        id=unit_id,
        document_version_id=version_id,
        document_id=document_id,
        section_id="sec-1",
        ordinal=ordinal,
        text=text,
        content_hash=hash_text(text),
        locator=f"§{ordinal + 1}",
    )


def seed_units(
    catalog: Catalog,
    scope: KnowledgeTenantScope,
    rows: list[tuple[str, str, list[float], str, int]],
) -> None:
    units = [
        make_unit(
            unit_id=unit_id,
            text=text,
            document_id=document_id,
            ordinal=ordinal,
        )
        for unit_id, text, _vector, document_id, ordinal in rows
    ]
    embeddings = [row[2] for row in rows]
    upsert_text_units(catalog, units, scope=scope, embeddings=embeddings)
