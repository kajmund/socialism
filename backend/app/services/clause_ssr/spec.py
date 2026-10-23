"""Embedding identity for clause SSR. Uses the open catalog dimension."""

from app.config import settings
from app.services.overgraph.catalogs import Catalog

from app.services.clause_ssr.types import EmbeddingSpec


def catalog_embedding(catalog: Catalog) -> EmbeddingSpec:
    return EmbeddingSpec(
        model=settings.embedding_model,
        revision=settings.embedding_model_revision,
        dimension=catalog.dimension,
    )
