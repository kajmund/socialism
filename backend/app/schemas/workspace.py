"""Public workspace contracts shared by HTTP commands and ElevenLabs tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.underlag_schemas import DocumentKnowledgeAnchorWrite


class WorkspaceDocumentTab(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    reference_id: str | None = None
    page: int = Field(default=1, ge=1)
    zoom: float = Field(default=1, ge=0.25, le=4)


class WorkspaceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str | None = None
    source_id: str | None = None
    source_version: str | None = Field(default=None, min_length=64, max_length=64)
    source_file_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    anchor: DocumentKnowledgeAnchorWrite | None = None
    artifact_id: str | None = None
    artifact_revision: int | None = Field(default=None, ge=1)
    block_id: str | None = None
    node_id: str | None = None
    edge_id: str | None = None


class WorkspaceState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["sv", "en", "nb"] = "sv"
    expert_id: str | None = None
    knowledge_scope: Literal["workspace", "general", "research"] = "workspace"
    view: Literal["evidence", "comparison", "documents", "relations"] = "evidence"
    documents: list[WorkspaceDocumentTab] = Field(default_factory=list, max_length=20)
    split_source_ids: list[str] = Field(default_factory=list, max_length=2)
    selection: WorkspaceSelection | None = None
    research_attempt_ids: list[str] = Field(default_factory=list, max_length=50)
    active_artifact_id: str | None = None


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=160)
    workspace_id: str | None = Field(default=None, max_length=64)
    chat_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    module: str = "dd"
    language: Literal["sv", "en", "nb"] = "sv"


class WorkspacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    state: WorkspaceState | None = None
    idempotency_key: str = Field(min_length=1, max_length=160)


class WorkspaceSourceAdd(BaseModel):
    source_id: str
    idempotency_key: str = Field(min_length=1, max_length=160)


class WorkspaceToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=160)
    expected_revision: int | None = Field(default=None, ge=0)
    arguments: dict = Field(default_factory=dict)


class WorkspaceArtifactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: dict
