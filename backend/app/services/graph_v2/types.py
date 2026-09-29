"""Extraction input and semantic decision seams for the graph core."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from app.services.knowledge.scope import KnowledgeTenantScope

Decision = Literal["SAME", "DISTINCT", "CONTRADICTS"]


@dataclass(frozen=True)
class NodeInput:
    node_type: str
    name: str
    scope: KnowledgeTenantScope
    identifier_namespace: str | None = None
    identifier: str | None = None
    context_key: str = ""
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceRef:
    kind: Literal["text_unit", "episode"]
    ref: str


@dataclass(frozen=True)
class FactInput:
    source_id: str
    target_id: str
    scope: KnowledgeTenantScope
    predicate: str
    fact_text: str
    sources: tuple[SourceRef, ...]
    context_id: str | None = None
    occurrence_key: str = ""
    valid_at: datetime | None = None
    embedding: tuple[float, ...] | None = None
    embedding_model: str | None = None
    attributes: dict[str, object] = field(default_factory=dict)


class NodeJudge(Protocol):
    async def same_node(self, proposed: NodeInput, candidate_name: str) -> bool: ...


class FactJudge(Protocol):
    async def compare(self, proposed: FactInput, candidate_text: str) -> Decision: ...


class TextEmbedder(Protocol):
    model: str
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
