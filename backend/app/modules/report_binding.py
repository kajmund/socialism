"""Report-mode → module dispatch types. No fallbacks: unknown mode is an error."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class UnknownReportModeError(ValueError):
    """Raised when Report.mode is not claimed by exactly one ModuleManifest."""

    def __init__(self, mode: str, *, matches: list[str] | None = None) -> None:
        self.mode = mode
        self.matches = matches or []
        if self.matches:
            claimed = ", ".join(self.matches)
            message = f"Report mode {mode!r} is claimed by multiple modules: {claimed}"
        else:
            message = f"Unknown report mode {mode!r}: no module claims it"
        super().__init__(message)


@dataclass(frozen=True)
class ReportGenerateContext:
    report_id: str
    title: str
    locale: str
    sources: list[dict[str, Any]]
    mode: str
    out_dir: Path
    session_factory: async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class ReportGenerateResult:
    html_path: Path
    slots_path: Path
    timing: dict[str, Any]


@dataclass(frozen=True)
class ReportBinding:
    """Per-module report pipeline. ``modes`` live on ModuleManifest.report_modes."""

    source_types: frozenset[str]
    generate: Callable[[ReportGenerateContext], Awaitable[ReportGenerateResult]]
