"""Validate published artifacts and their workspace-bound source references."""

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.workspace_models import Workspace, WorkspaceArtifact
from app.services.workspace.sources import read_reference


class ContentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_refs: list[str] = Field(default_factory=list)


class Block(ContentItem):
    id: str = Field(min_length=1)
    type: Literal["heading", "paragraph"]
    text: str


class Cell(ContentItem):
    text: str | None

    @model_validator(mode="after")
    def require_basis(self):
        if self.text is not None and not self.source_refs:
            raise ValueError("comparison_cell_source_required")
        return self


class Row(BaseModel):
    id: str = Field(min_length=1)
    label: str
    cells: list[Cell]


class Node(ContentItem):
    id: str = Field(min_length=1)
    label: str
    kind: Literal["event", "condition", "effect", "interpretation"]
    @model_validator(mode="after")
    def require_basis(self):
        if self.kind != "interpretation" and not self.source_refs:
            raise ValueError("relation_fact_source_required")
        return self


class Edge(ContentItem):
    id: str = Field(min_length=1)
    source: str
    target: str
    label: str
    interpretation: bool
    @model_validator(mode="after")
    def require_basis(self):
        if not self.interpretation and not self.source_refs:
            raise ValueError("relation_edge_source_required")
        return self


def _unique_ids(values: list) -> set[str]:
    identifiers = {value.id for value in values}
    if len(identifiers) != len(values):
        raise ValueError("duplicate_artifact_item")
    return identifiers


def _document(content: dict) -> None:
    blocks = [Block.model_validate(value) for value in content["blocks"]]
    if not blocks:
        raise ValueError("document_blocks_required")
    _unique_ids(blocks)


def _comparison(content: dict) -> None:
    columns = content["columns"]
    rows = [Row.model_validate(value) for value in content["rows"]]
    if not columns or any(not isinstance(column, str) for column in columns):
        raise ValueError("comparison_columns_required")
    _unique_ids(rows)
    if any(len(row.cells) != len(columns) for row in rows):
        raise ValueError("invalid_comparison_row")


def _relations(content: dict) -> None:
    nodes = [Node.model_validate(value) for value in content["nodes"]]
    edges = [Edge.model_validate(value) for value in content["edges"]]
    identifiers = _unique_ids(nodes)
    _unique_ids(edges)
    if any(edge.source not in identifiers or edge.target not in identifiers for edge in edges):
        raise ValueError("invalid_relation_endpoint")


def _references(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source_refs":
                if not isinstance(item, list) or any(not isinstance(ref, str) for ref in item):
                    raise ValueError("invalid_source_refs")
                refs.update(item)
            else:
                refs.update(_references(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_references(item))
    return refs


async def validate_artifact_content(session: AsyncSession, artifact: WorkspaceArtifact, content: dict) -> None:
    workspace = await session.get(Workspace, artifact.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="workspace_not_found")
    validators = {"document": _document, "comparison": _comparison, "relations": _relations}
    try:
        refs = _references(content)
        if artifact.kind in validators:
            validators[artifact.kind](content)
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="invalid_artifact_content") from exc
    for reference_id in refs:
        reference = await read_reference(session, workspace, reference_id)
        if reference["stale"]:
            raise HTTPException(status_code=409, detail="workspace_reference_stale")
