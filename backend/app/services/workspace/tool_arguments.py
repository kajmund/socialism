"""Strict argument contracts for workspace commands."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArguments(ToolArguments):
    query: str = Field(min_length=1, max_length=4000)
    scope: Literal["workspace", "general", "research"] | None = None
    limit: int = Field(default=10, ge=1, le=30)


class ReadArguments(ToolArguments):
    reference_id: str | None = None
    source_id: str | None = None


class IngestArguments(ToolArguments):
    source_id: str | None = None
    url: str | None = Field(default=None, max_length=2048)


class JobArguments(ToolArguments):
    job_id: str | None = None
    attempt_id: str | None = None


class GenerationArguments(ToolArguments):
    title: str = Field(default="", max_length=255)
    instructions: str = Field(default="", max_length=10000)
    topic: str = Field(default="", max_length=4000)
    document_type: str = Field(default="summary", max_length=64)
    source_refs: list[str] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    language: Literal["sv", "en", "nb"] = "sv"


class ReviseArguments(ToolArguments):
    artifact_id: str
    expected_revision: int = Field(ge=1)
    block_id: str | None = None
    instructions: str = Field(default="", max_length=10000)
    content: dict | None = None
    title: str | None = Field(default=None, max_length=255)
    language: Literal["sv", "en", "nb"] = "sv"


class ExportArguments(ToolArguments):
    artifact_id: str
    revision: int = Field(ge=1)
    format: Literal["docx", "pdf"]


class ChartSeries(ToolArguments):
    label: str = Field(min_length=1, max_length=255)
    value: float = Field(allow_inf_nan=False)


class ChartArguments(ToolArguments):
    title: str = Field(min_length=1, max_length=255)
    chart_type: Literal["hbar", "donut", "stat_number", "radar"]
    series: list[ChartSeries] = Field(min_length=1, max_length=100)
    source_refs: list[str] = Field(min_length=1, max_length=50)


class ResearchArguments(ToolArguments):
    objective: str = Field(min_length=1, max_length=4000)
    confirmed: bool = False
    source_object_ids: list[str] | None = Field(default=None, max_length=100)
