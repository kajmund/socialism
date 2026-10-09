"""Strict argument contracts for workspace commands."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArguments(ToolArguments):
    query: str = Field(min_length=1, max_length=4000)
    scope: Literal["workspace", "general", "research"] | None = None
    limit: int = Field(default=10, ge=1, le=30)
    source_id: str | None = Field(
        default=None,
        max_length=64,
        description="source_object_id när dokumentet redan är identifierat. Utelämna för att söka i arbetsytans dokument.",
    )
    exact: bool = Field(
        default=False,
        description="Sant när textsträngen redan är känd. Matchar den i befintliga textenheter utan semantisk sökning.",
    )


class ReadArguments(ToolArguments):
    reference_id: str | None = None
    source_id: str | None = None
    quote: str | None = Field(
        default=None,
        max_length=500,
        description="Känd passage. Läser stycken runt den. Flyttar inte vyn.",
    )
    section: str | None = Field(
        default=None,
        max_length=255,
        description="Rubrik eller klausul som redan finns i dokumentstrukturen från ingest.",
    )
    outline: bool = Field(
        default=False,
        description="Returnera rubriker och sektioner från ingest. Läser inte hela dokumentet.",
    )
    page: int | None = Field(
        default=None,
        ge=1,
        description="Sida från 1. Läser textenheterna på den sidan. Flyttar inte vyn.",
    )
    paragraphs: int = Field(default=2, ge=0, le=8)

    @model_validator(mode="after")
    def one_read_target(self) -> "ReadArguments":
        chosen = (self.quote is not None, self.section is not None, self.outline, self.page is not None)
        if sum(bool(item) for item in chosen) > 1:
            raise ValueError("one_read_target")
        return self


class FocusPassageArguments(ToolArguments):
    source_id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=4000)


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
