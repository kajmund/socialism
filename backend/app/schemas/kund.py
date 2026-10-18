"""Customer / project scoping schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


from app.schemas.profiles import OrganizationFields


class ProjektOut(BaseModel):
    id: int
    customer_id: int
    name: str
    slug: str


class KundOut(OrganizationFields):
    id: int
    name: str
    slug: str
    product: str | None = None
    available_modules: list[str] = Field(default_factory=list)
    projekt: list[ProjektOut] = Field(default_factory=list)


class KundCreate(OrganizationFields):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64)
    product: str | None = None
    available_modules: list[str] = Field(default_factory=list)


class KundUpdate(OrganizationFields):
    product: str | None = None
    available_modules: list[str] | None = None


class KundDocumentCountsOut(BaseModel):
    files: int = 0
    knowledge_documents: int = 0
    canonical_documents: int = 0
    text_units: int = 0
    document_knowledge_items: int = 0
    claims: int = 0
    entities: int = 0
    relationships: int = 0
    graph_events: int = 0
    graph_facts: int = 0
    graph_nodes: int = 0
    ingest_batches: int = 0


class KundDocumentsOut(BaseModel):
    kund_id: int
    kund_name: str
    kund_slug: str
    counts: KundDocumentCountsOut
    blocked_reason: str | None = None


class KundDocumentsDeletedOut(BaseModel):
    kund_id: int
    deleted: KundDocumentCountsOut
    vector_documents: int
    stored_objects: int
